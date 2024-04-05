import os
import re
import json


class FaultUtils:
    """Utility class for page faults

    This class provides some utility functions for determining the type of page
    faults given the flags defined in Linux kernel. This should be used with
    kprobe trace.

    @see: https://github.com/torvalds/linux/blob/v6.8/include/linux/mm_types.h#L1213
    @see: https://github.com/torvalds/linux/blob/v6.8/include/linux/mm_types.h#L1327
    """
    VM_FAULT_OOM            = 0x000001
    VM_FAULT_SIGBUS         = 0x000002
    VM_FAULT_MAJOR          = 0x000004
    VM_FAULT_HWPOISON       = 0x000010
    VM_FAULT_HWPOISON_LARGE = 0x000020
    VM_FAULT_SIGSEGV        = 0x000040
    VM_FAULT_RETRY          = 0x000400
    VM_FAULT_FALLBACK       = 0x000800
    VM_FAULT_DONE_COW       = 0x001000
    VM_FAULT_ERROR          = VM_FAULT_OOM | VM_FAULT_SIGBUS | VM_FAULT_SIGSEGV | VM_FAULT_HWPOISON | \
        VM_FAULT_HWPOISON_LARGE | VM_FAULT_FALLBACK

    FAULT_FLAG_WRITE        = 1 << 0
    FAULT_FLAG_TRIED        = 1 << 5
    FAULT_FLAG_USER         = 1 << 6

    @classmethod
    def should_trace(cls, ret, flags):
        """
        Checks if the detected page fault event needs to be considered. The
        logic is the same as the `mm_account_fault()` function in Linux kernel,
        which records system minor and major page fault statistics.

        @see: https://github.com/torvalds/linux/blob/v6.8/mm/memory.c#L5323
        """
        if bool(ret & cls.VM_FAULT_RETRY):
            return False
        if bool(ret & cls.VM_FAULT_ERROR):
            return False
        return True

    @classmethod
    def is_major(cls, ret, flags):
        """
        Checks if the page fault event is a major page fault.

        @see: https://github.com/torvalds/linux/blob/v6.8/mm/memory.c#L5355
        """
        if not cls.should_trace(ret, flags):
            raise ValueError(f'should not trace this fault with ret={hex(ret)} and flags={hex(flags)}')
        return bool(ret & cls.VM_FAULT_MAJOR) or bool(flags & cls.FAULT_FLAG_TRIED)

    @classmethod
    def is_cow(cls, ret, flags):
        """
        Checks if the minor page fault is a COW fault or a regular "lazy" fault.

        TODO: may need to examine whether pte is writable (hard)
        TODO: flag test incorrect
        @see: https://github.com/torvalds/linux/blob/v6.8/mm/memory.c#L5180
        @see: https://github.com/torvalds/linux/blob/v6.8/mm/memory.c#L4399
        """
        if not cls.should_trace(ret, flags):
            raise ValueError(f'should not trace this fault with ret={hex(ret)} and flags={hex(flags)}')
        if cls.is_major(ret, flags):
            raise ValueError(f'invalid minor fault (should be major)')  # should not come here
        return bool(flags & (cls.FAULT_FLAG_WRITE | cls.FAULT_FLAG_USER)) \
            or bool(ret & cls.VM_FAULT_DONE_COW)


class Fault:
    """Fault data class

    This class contains all the information needed of a page fault for analysis.
    """
    def __init__(self):
        self.pid = -1        # process id
        self.cpu = -1        # cpu id
        self.timestamp = -1  # timestamp in microseconds
        self.address = -1    # faulting address
        self.flags = 0       # fault flags
        self.ret = 0         # page fault handler's return value
        self.type = None     # type of page fault

    def is_valid(self):
        """
        Checks if this fault instance contains valid information.
        """
        return (self.pid != -1 and self.cpu != -1 and self.timestamp != -1
                and self.address != -1 and self.type is not None)

    def test_type(self):
        """
        Assigns the proper type to this fault instance given the information.
        - 'ignore' means the fault should be simply ignored.
        - 'maj' means a major page fault.
        - 'cow' means a COW minor page fault.
        - 'min' means a reqular minor page fault.
        """
        if not FaultUtils.should_trace(self.ret, self.flags):
            self.type = 'ignore'
        elif FaultUtils.is_major(self.ret, self.flags):
            self.type = 'maj'
        elif FaultUtils.is_cow(self.ret, self.flags):
            self.type = 'cow'
        else:
            self.type = 'min'


class FaultParser:
    _arg_expr = re.compile(r'\-(\d+)\s+\[(\d+)\][\s\.]+(\d+\.\d+):.+address=(\w+) flag=(\w+)')
    _ret_expr = re.compile(r'\-(\d+)\s+\[(\d+)\][\s\.]+\d+\.\d+:.+ret=(\d+)')

    def __init__(self, filepath):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f'{filepath} does not exist')
        self._filepath = filepath

    def parse(self):
        _idx = 0
        _faults = []
        with open(self._filepath, 'r') as f:
            for line in f.readlines():
                line = line.strip('\n')
                r = re.search(self._arg_expr, line)
                if r is not None:
                    flt = Fault()
                    flt.pid = int(r.group(1))
                    flt.cpu = int(r.group(2))
                    flt.timestamp = int(r.group(3).replace('.', ''))
                    flt.address = hex(int(r.group(4), 16))
                    flt.flags = hex(int(r.group(5), 16))
                    _faults.append(flt)
                    continue
                r = re.search(self._ret_expr, line)
                if r is not None:
                    pid = int(r.group(1))
                    cpu = int(r.group(2))
                    if _faults[_idx].pid == pid and _faults[_idx].cpu == cpu:
                        _faults[_idx].ret = int(r.group(3))
                        _faults[_idx].test_type()  # determine the type of fault
                        _idx += 1
                    else:
                        print(f'found a dangling ret line: {line}')  # should never reach here
        return _faults


class Frame:
    def __init__(self):
        self.pid = -1
        self.fid = -1
        self.lineno = -1
        self.timestamp = -1
        self.filename = None


class FrameParser:
    def __init__(self, filepath):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f'{filepath} does not exist')
        self._filepath = filepath

    def parse(self):
        frames = []
        with open(self._filepath, 'r') as f:
            for line in f.readlines():
                line = line.strip('\n')
                toks = line.split(',')
                fr = Frame()
                fr.pid = int(toks[0])
                fr.fid = int(toks[1])
                fr.lineno = int(toks[2])
                fr.timestamp = int(int(toks[3]) / 1000)
                fr.filename = toks[4]
                frames.append(fr)
        return frames


class Proc:
    def __init__(self):
        self.pid = -1
        self.ppid = -1
        self.timestamp = -1


class ProcParser:
    def __init__(self, filepath):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f'{filepath} does not exist')
        self._filepath = filepath

    def parse(self):
        procs = []
        skip_first = False
        with open(self._filepath, 'r') as f:
            for line in f.readlines():
                if not skip_first:
                    skip_first = True
                    continue

                line = line.strip('\n')
                toks = line.split(',')
                pr = Proc()
                pr.pid = int(toks[1])
                pr.ppid = int(toks[0])
                pr.timestamp = int(int(toks[3]) / 1000)
                procs.append(pr)
        return procs 


class TraceOutput:
    def __init__(self, faults, procs, frames, root_pid):
        self.procs = {'root': root_pid, 'rels': procs}
        self.faults = faults
        self.frames = frames

    def save(self, file):
        with open(file, 'w') as f:
            json.dump(self, f, default=lambda o: o.__dict__, indent=4)

