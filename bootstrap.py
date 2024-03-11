import os
import sys
import signal
import argparse

_original_fork = os.fork
_pid_file = '/tmp/fatras/pids.txt'  # agreed to write to this file


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
        # 2. start line-level profiling (lieno, code, file)
        # 3. register stop-profile function atexit
        pass
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
