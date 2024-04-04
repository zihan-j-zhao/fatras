import os
import re


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
        if bool(flags & cls.VM_FAULT_ERROR):
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
        @see: https://github.com/torvalds/linux/blob/v6.8/mm/memory.c#L5180
        @see: https://github.com/torvalds/linux/blob/v6.8/mm/memory.c#L4399
        """
        if not cls.should_trace(ret, flags):
            raise ValueError(f'should not trace this fault with ret={hex(ret)} and flags={hex(flags)}')
        return not cls.is_major(ret, flags) and (bool(flags & (cls.FAULT_FLAG_WRITE | cls.FAULT_FLAG_USER))
                                                 or bool(ret & cls.VM_FAULT_DONE_COW))


class Fault:
    def __init__(self):
        self.pid = -1
        self.cpu = -1
        self.timestamp = -1
        self.address = -1
        self.flags = 0
        self.ret = 0
        self.type = None

    def is_valid(self):
        return (self.pid != -1 and self.cpu != -1 and self.timestamp != -1
                and self.address != -1 and self.type is not None)

    def test_type(self):
        if self.is_valid():
            if not FaultUtils.should_trace(self.ret, self.flags):
                self.type = 'ignore'
            elif FaultUtils.is_major(self.ret, self.flags):
                self.type = 'maj'
            elif FaultUtils.is_cow(self.ret, self.flags):
                self.type = 'cow'
            else:
                self.type = 'min'


class FaultParser:
    _arg_expr = re.compile(r'\-(\d+)\s+\[(\d+)\][\s\.]+(\d+\.\d+):.+address=(\w+) flags=(\w+)')
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
                line = line.strip()
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
                        _faults[_idx].ret = int(r.group(1))
                        _faults[_idx].test_type()  # determine the type of fault
                        _idx += 1
                    else:
                        print(f'found a dangling ret line: {line}')  # should never reach here
        return _faults

