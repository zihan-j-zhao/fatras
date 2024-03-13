import re
import json

_fault_expr = re.compile(r"^.*-(\d+) .* (\d+\.\d+): .*fault_user: address=(0x[\d\w]+) .* error_code=(0x[\d\w]+)$")


class PageFault:
    def __init__(self, s_pid, s_timestamp, s_address, s_error_code):
        self.pid = int(s_pid)
        self.address = s_address
        self.timestamp = int(s_timestamp.replace('.', ''))
        self.type = 'maj' if s_error_code == '0x6' else 'min'

    @staticmethod
    def is_maj_or_min(s_error_code):
        return s_error_code == '0x6' or s_error_code == '0x7'

    @staticmethod
    def from_trace(file):
        faults = []
        with open(file, 'r') as f:
            for line in f.readlines():
                line = line.strip()
                r = re.search(_fault_expr, line)
                if r is not None and PageFault.is_maj_or_min(r.group(4)):
                    faults.append(PageFault(r.group(1), r.group(2), r.group(3), r.group(4)))
        return faults


class ForkEvent:
    def __init__(self, s_ppid, s_pid, s_timestamp):
        self.ppid = int(s_ppid)
        self.pid = int(s_pid)
        self.timestamp = int(int(s_timestamp) / 1e3)

    @staticmethod
    def from_pids(file):
        procs = []
        with open(file, 'r') as f:
            for line in f.readlines():
                tokens = line.strip().split(',')
                if len(tokens) == 3:
                    procs.append(ForkEvent(tokens[0], tokens[1], tokens[2]))
        return procs


class FrameTrace:
    def __init__(self, s_lineno, s_timestamp, s_file_path):
        self.lineno = int(s_lineno)
        self.timestamp = int(int(s_timestamp) / 1e3)
        self.file_path = s_file_path

    @staticmethod
    def from_frame(file):
        code = []
        with open(file, 'r') as f:
            for line in f.readlines():
                tokens = line.strip().split(',')
                code.append(FrameTrace(tokens[0], tokens[1], tokens[2]))
        return code


class Data:
    def __init__(self, faults, forks, frames, root_pid):
        self.forks = {'root': root_pid, 'rels': forks}
        self.faults = faults
        self.frames = frames

    def save(self, file):
        with open(file, 'w') as f:
            json.dump(self, f, default=lambda o: o.__dict__, indent=4)
