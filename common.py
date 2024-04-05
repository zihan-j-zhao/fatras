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

        self.error = -1      # error code (specific to x86 arch)

    def test_type(self):
        """
        Assigns the proper type to this fault instance given the information.
        - 'ignore' means the fault should be simply ignored.
        - 'maj' means a major page fault.
        - 'cow' means a COW minor page fault.
        - 'min' means a regular minor page fault.
        """
        if not FaultUtils.should_trace(self.ret, self.flags):
            self.type = 'ignore'
        elif self.error == 0x7:
            self.type = 'cow'
        elif FaultUtils.is_major(self.ret, self.flags):
            self.type = 'maj'
        else:
            self.type = 'min'


class FaultParser:
    _pid_expr = re.compile(r'\-(\d+)\s+')
    _err_expr = re.compile(r'\-(\d+)\s+\[(\d+)\][\s\.d]+(\d+\.\d+):.+address=(\w+).*error_code=(\w+)')
    _arg_expr = re.compile(r'\-(\d+)\s+\[(\d+)\][\s\.]+(\d+\.\d+):.+address=(\w+) flag=(\w+)')
    _ret_expr = re.compile(r'\-(\d+)\s+\[(\d+)\][\s\.]+\d+\.\d+:.+ret=(\d+)')

    def __init__(self, filepath):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f'{filepath} does not exist')
        self._filepath = filepath

    def __split_by_pid(self):
        from record import _pid_file

        pids = set()
        with open(_pid_file, 'r') as f:
            skip_first = False
            for line in f.readlines():
                if not skip_first:
                    skip_first = True
                    continue

                line = line.strip('\n')
                toks = line.split(',')
                pids.add(int(toks[0]))
                pids.add(int(toks[1]))

        files = {}
        for pid in pids:
            file = f'/tmp/fatras/trace_{pid}.tmp'
            open(file, 'w+').close()  # clear old content
            files[pid] = open(file, 'a+')

        with open(f'{self._filepath}', 'r') as f:
            for line in f.readlines():
                r = re.search(self._pid_expr, line)
                if r is not None:
                    pid = int(r.group(1))
                    if pid not in files:
                        continue  # TODO: weird child, not patch-forked
                    files[pid].write(line)

        for pid in pids:
            files[pid].close()

        return pids

    def parse(self):
        pids = self.__split_by_pid()
        _faults = []
        for pid in pids:
            with open(f'/tmp/fatras/trace_{pid}.tmp', 'r') as f:
                flag = False
                for line in f.readlines():
                    line = line.strip('\n')
                    r = re.search(self._err_expr, line)
                    if r is not None:
                        flag = True  # align with the first page_fault_user event
                        flt = Fault()
                        flt.pid = int(r.group(1))
                        flt.cpu = int(r.group(2))
                        flt.timestamp = int(r.group(3).replace('.', ''))
                        flt.address = hex(int(r.group(4), 16))
                        flt.error = int(r.group(5), 16)
                        _faults.append(flt)
                        continue
                    if not flag:
                        continue  # skip the first couple of unaligned traces
                    r = re.search(self._arg_expr, line)
                    if r is not None:  # guaranteed to be not None
                        _faults[-1].flags = int(r.group(5), 16)  # record flags
                        continue
                    r = re.search(self._ret_expr, line)
                    if r is not None: # guaranteed to be not None
                        _faults[-1].ret = int(r.group(3))  # record return value
                        _faults[-1].test_type()
                        continue
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
                pr.timestamp = int(int(toks[2]) / 1000)
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

