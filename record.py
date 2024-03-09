def handle_record(args):
    # 0. [main] clear and then set up ftrace
    # 1. fork a child proc to wait to read from trace_pipe
    # 2. fork a child proc to execute the given program
    #   2.1 Popen the program through bootstrap.py and custom CPython build
    #     2.1.1 add tracing flags to various alloc functions, e.g. gc, raw
    #     2.1.2 write data to files after allocation, e.g. realloc, new_arena
    #     2.1.3 write based on the given precision level (prepare 3 builds for 3 levels)
    #   2.2 patch necessary functions in bootstrap.py, e.g. os.fork
    #   2.3 register line-level (0.01s) signals in bootstrap.py
    #   2.4 compile the given program and exec it with locals and globals
    #   2.5 signal the other child proc to stop when run to completion
    # 3. clean up and save the data in trace.dat
    #   3.1 [child 1] disable ftrace and then clear settings
    #   3.2 group data (line-of-code, page faults, etc.) into a data structure
    #   3.3 serialize the data in binary to the output file (e.g. trace.dat)
    pass
