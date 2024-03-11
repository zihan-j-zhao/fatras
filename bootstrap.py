import os
import sys
import time
import atexit
import signal
import inspect
import argparse


_cwd = os.getcwd()
_original_fork = os.fork
_pid_file = '/tmp/fatras/pids.txt'  # agreed to write to this file
_frame_file = '/tmp/fatras/frames.txt'
_frame_file_handle = None


#################################################
#
# Line-level Tracing
#
#################################################


def fwrite_frame(frame):
    global _frame_file_handle
    if not _frame_file_handle:
        open(_frame_file, 'w+').close()  # create and empty the file
        _frame_file_handle = open(_frame_file, 'a+')
        atexit.register(lambda: _frame_file_handle.close())  # close file at exit

    lineno = inspect.getlineno(frame)
    filename = inspect.getfile(frame)
    timestamp = time.monotonic_ns()

    _frame_file_handle.write(f'{lineno},{timestamp},{filename}\n')


def should_trace(frame):
    """
    Returns True if the current frame or one of the frames on the stack trace
    corresponds to code in files under the initial current working directory.
    False otherwise.
    """
    if frame is None:
        return False

    # TODO: maybe allow regex match with command-line input
    return inspect.getframeinfo(frame).filename.startswith(_cwd)


def trace(signum, frame):
    """
    Writes line-level tracing to file whenever signalled to do so.
    """
    # find the closest frame of interest
    while frame is not None and not should_trace(frame):
        frame = frame.f_back

    # ignore this frame
    if frame is None:
        return

    # write frame info to file
    fwrite_frame(frame)


#################################################
#
# Bootstrap
#
#################################################


def fwrite_pids(ppid, pid):
    """
    Writes pids to file as a way to share data across processes.
    """
    with open(_pid_file, 'a+') as f:
        f.write(f'{ppid},{pid}\n')


def replacement_fork():
    """
    Patches the system fork to insert tracing functionalities.
    """
    # 1. write pid to file (ppid, pid)
    pid = _original_fork()
    if pid:
        fwrite_pids(os.getpid(), pid)
    else:
        # 2. start line-level tracing
        signal.signal(signal.SIGVTALRM, trace)
        signal.setitimer(signal.ITIMER_VIRTUAL, 0.01, 0.01)

        # 3. register stop-trace function atexit
        atexit.register(lambda: signal.signal(signal.SIGVTALRM, signal.SIG_DFL))
    return pid


def start_process(args):
    """
    Starts the program with given arguments after patching all the necessary
    variables, functions, etc. Meanwhile, this function signals the sentinel
    process to enable and disable ftrace before and after the program is
    executed. Regardless of whether the program runs to completion without
    exceptions, the signals will always be sent to ensure the states of ftrace
    are managed safely adn correctly.
    """
    bootstrap_pid = os.getpid()
    prog = args.program[0]
    if not os.path.exists(prog):
        raise FileNotFoundError(prog)

    # write the "parent" pid to file first
    with open(_pid_file, 'w+') as f:
        f.write(f'{bootstrap_pid}\n')

    # prepare the execution environment
    # TODO: any more vars to be patched?
    sys.argv = sys.argv[2:]
    os.fork = replacement_fork

    # signal to start ftrace
    os.kill(args.sentinel_pid, signal.SIGUSR1)

    try:
        # execute the target program (os.fork is patched)
        exec(open(prog, 'r').read(), globals(), locals())

        # wait for all child procs to completion
        while True: os.wait()
    except ChildProcessError as e:  # expect to happen
        print('all child processes terminated normally')
    finally:
        # signal to stop ftrace in parent
        if bootstrap_pid == os.getpid():
            os.kill(args.sentinel_pid, signal.SIGUSR2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='fatras bootstrap',
        description='A bootstrap script to prepare program for tracing',
    )

    # required
    parser.add_argument(
        'sentinel_pid',
        help='the pid of the sentinel process',
        type=int,
    )

    # required
    parser.add_argument(
        'program',
        nargs='+',
        help='the program to be recorded',
        type=str,
    )

    args = parser.parse_args()
    start_process(args)
