# main.py (entry point of fatras)
# fatras record prog.py
# fatras report -i trace.dat --output "[pid]_out.txt"

import argparse
from record import handle_record


def add_command_record(parser):
    """
    This command runs the given Python program, collects
    page fault statistics of the process (and of its child
    processes, by default), and saves the data in the file
    "trace.dat", by default, under the current directory.

    Note that many intermediate files will be generated
    while recording, but at the end, only one file will be
    produced (i.e. trace.dat or the designated output file),
    and all the intermediate files will be deleted promptly.

    ATTENTION! Before recording starts, all the existing
    ftrace settings will be cleared for correctness. Make
    sure to save your settings in advance.
    """

    record_parser = parser.add_parser(
        'record', 
        description='Records page fault statistics of the Python process(es)',
        usage='%(prog)s [options] <file>',
    )

    # required
    record_parser.add_argument(
        'file', 
        nargs=1, 
        help='the Python program to be recorded',
        type=str,
    )

    # optional
    record_parser.add_argument(
        '--no-children',
        action='store_true',
        default=False,
        help='ignore all child processes spawned',
    )

    # optional
    record_parser.add_argument(
        '-o', '--output',
        nargs=1,
        default='trace.dat',
        help='the file that saves recorded page fault stats',
        type=str,
    )

    # optional
    record_parser.add_argument(
        '--precision',
        nargs='?',
        choices=range(1,4),
        default=2,
        help='the precision level of tracing (the higher, the slower)',
        type=int,
    )

    record_parser.set_defaults(func=handle_record)


def add_command_report(parser):
    """
    This command looks for the trace.dat file to generate a
    human-readable file or a format that can be easily used
    for next-step processing, such as json. If the trace.dat
    file does not exist, the user must specify the name of
    the file through flags.
    """

    report_parser = parser.add_parser(
        'report',
        description='Generates a human-readable summary of the recorded stats',
        usage='%(prog)s [options]'
    )

    # optional
    report_parser.add_argument(
        '-i', '--input',
        nargs=1,
        default='trace.dat',
        help='the data file produced by the record command',
        type=str,
    )

    # optional
    report_parser.add_argument(
        '-o', '--output',
        nargs=1,
        default='[pid]_results.txt',
        help='the file(s) containing the results',
        type=str,
    )

    # optional
    report_parser.add_argument(
        '--format',
        nargs=1,
        choices=['txt', 'json'],
        default='txt',
        help='the format of the output file',
        type=str,
    )

    # report_parser.set_defaults(func=handle_report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='fatras', 
        description='A fine-grained Python page fault analyzer',
        epilog='Email zihan.j.zhao@gmail.com for more questions',
    )
    subparsers = parser.add_subparsers(
        title='Supported Subcommands',
        required=True,
    )

    # subcommands
    add_command_record(subparsers)
    add_command_report(subparsers)

    args = parser.parse_args()
    print(args)
