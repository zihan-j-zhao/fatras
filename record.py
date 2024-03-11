import os
import sys
import time
import atexit
import signal
import subprocess

_ftrace_path = '/sys/kernel/tracing'
_pid_file = '/tmp/fatras/pids.txt'
_trace_file = '/tmp/fatras/trace.txt'

_max_timeout = 60 * 60  # 1 hour


def fwrite(path, text):
    with open(path, 'w') as f:
        f.write(text)


def is_linux():
    """
    Checks if the current operating system is Linux.
    """
    return sys.platform == 'linux' or sys.platform == 'linux2'


def exist_ftrace():
    """
    Checks if the ftrace pseudo file system is mounted.
    """
    return os.path.exists(_ftrace_path)


def exist_trace_cmd():
    """
    Checks if the trace-cmd tool is installed.
    """
    return subprocess.call(['which', 'trace-cmd']) == 0


def reset_ftrace():
    """
    Resets ftrace tracing completely - clearing out all tracing settings and
    disabling everything.

    @see: https://docs.kernel.org/trace/ftrace.html
    @see (deprecated): https://man7.org/linux/man-pages/man1/trace-cmd-reset.1.html
    """
    if not is_linux():
        raise OSError('platform not supported, Linux required')

    if not exist_ftrace():
        raise FileNotFoundError(f'{_ftrace_path}, try `mount -t tracefs nodev /sys/kernel/tracing`')

    fwrite(os.path.join(_ftrace_path, 'tracing_on'), '0')
    fwrite(os.path.join(_ftrace_path, 'trace_clock'), 'local')
    fwrite(os.path.join(_ftrace_path, 'options/event-fork'), '0')
    fwrite(os.path.join(_ftrace_path, 'events/exceptions/page_fault_user/enable'), '0')
    fwrite(os.path.join(_ftrace_path, 'set_event_pid'), '')


def setup_ftrace(ignore_children=False):
    """
    Sets up the ftrace configurations for tracing page faults for the given
    process and its child processes if ignore_children is False.
    """
    # reset ftrace
    reset_ftrace()

    # set up page fault configurations
    fwrite(os.path.join(_ftrace_path, 'trace_clock'), 'mono')  # in microseconds
    fwrite(os.path.join(_ftrace_path, 'events/exceptions/page_fault_user/enable'), '1')
    fwrite(os.path.join(_ftrace_path, 'buffer_size_kb'), '1024')
    fwrite(os.path.join(_ftrace_path, 'options/event-fork'), str(int(not ignore_children)))
    # fwrite(os.path.join(_ftrace_path, 'set_event_pid'), '???')  # set in start_sentinel
    # fwrite(os.path.join(_ftrace_path, 'tracing_on'), '1')  # set in start_sentinel


def read_ppid():
    """
    Reads the pid of the "parent" process from an auto-generated pid file that
    records all relationships between processes. Users should not need to worry
    about the pid file and this procedure.
    """
    if not os.path.exists(_pid_file):
        raise FileNotFoundError(f'{_pid_file} (auto-generated), rerun the command')

    with open(_pid_file, 'r') as f:
        pid = f.readline().strip('\n')
        if pid.isnumeric():
            return pid
        raise ValueError('ppid is not numeric, invalid pid file')


def start_sentinel():
    """
    Waits for signals sent from the process responsible for executing the
    program to enable or disable ftrace. While waiting, this function spins.
    Having enabled ftrace, this function begins to read trace data from
    trace_pipe until the pipe is closed by disabling ftrace.
    """
    _enabled = False
    _disabled = False

    def enable_ftrace(signum, frame):
        nonlocal _enabled
        if _enabled:
            print('Warning: double enabling ftrace is not allowed, signal ignored')
            return
        _enabled = True
        ppid = read_ppid()
        fwrite(os.path.join(_ftrace_path, 'set_event_pid'), ppid)
        fwrite(os.path.join(_ftrace_path, 'tracing_on'), '1')
        print('ftrace has started to monitor the parent process:', ppid)

    def disable_ftrace(signum, frame):
        nonlocal _disabled
        if _disabled:
            print('Warning: double disabling ftrace is not allowed, signal ignored')
            return
        _disabled = True
        fwrite(os.path.join(_ftrace_path, 'tracing_on'), '0')
        print('ftrace has stopped')

    open(_trace_file, 'w+').close()  # create an empty file or clear old data
    signal.signal(signal.SIGUSR1, enable_ftrace)
    signal.signal(signal.SIGUSR2, disable_ftrace)
    atexit.register(reset_ftrace)  # clean up

    while not _enabled:
        time.sleep(.5)  # wait a bit

    with open(os.path.join(_ftrace_path, 'trace_pipe'), 'r') as f_from:
        with open(_trace_file, 'a+') as f_to:
            while True:
                line = f_from.readline()
                if not line:
                    print('ftrace data have been saved')
                    break
                f_to.write(line)


def start_bootstrap(sentinel_pid, args):
    """
    Bootstraps the given program and runs it. This function waits until the
    program completes so that data aggregation may begin.
    """
    command = [args.python[0], 'bootstrap.py', str(sentinel_pid), *args.program]
    subprocess.check_call(command, timeout=max(args.timeout, 0) or _max_timeout)


def handle_record(args):
    # 0. clear and then set up ftrace
    setup_ftrace(args.ignore_children)
    # 1. fork a child proc to wait to read from trace_pipe
    sentinel_pid = os.fork()
    if sentinel_pid == 0:
        return start_sentinel()
    # 2. fork a child proc to execute the given program
    pid = os.fork()
    if pid == 0:
        #   2.1 Popen the program through bootstrap.py and custom CPython build
        #     2.1.1 add tracing flags to various alloc functions, e.g. gc, raw
        #     2.1.2 write data to files after allocation, e.g. realloc, new_arena
        #   2.2 patch necessary functions in bootstrap.py, e.g. os.fork
        #   2.3 register line-level (0.01s) signals in bootstrap.py
        #   2.4 compile the given program and exec it with locals and globals
        #   2.5 signal the other child proc to clean up when run to completion
        return start_bootstrap(sentinel_pid, args)
    # 3. clean up and save the data in trace.dat
    os.waitpid(pid, 0)
    #   3.1 group data (line-of-code, page faults, etc.) into a data structure
    #   3.2 serialize the data in binary to the output file (e.g. trace.dat)
    return
