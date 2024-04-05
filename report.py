import os
import json


def load_trace(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)


def group_faults_by_pid(faults):
    groups = {}

    for fault in faults:
        pid = fault['pid']
        if pid not in groups:
            groups[pid] = [fault]
        else:
            groups[pid].append(fault)

    return groups


def group_frames_by_pid(frames):
    groups = {}

    for frame in frames:
        pid = frame['pid']
        if pid not in groups:
            groups[pid] = [frame]
        else:
            groups[pid].append(frame)

    return groups


def get_data_before(group, timestamp):
    data = []
    for element in group:
        if element['timestamp'] <= timestamp:
            data.append(element)
    return data


def get_cpus(faults):
    cpus = set()

    for fault in faults:
        if fault['cpu'] not in cpus:
            cpus.add(fault['cpu'])

    return cpus


def count_faults_by_types(faults):
    cow = 0
    min = 0
    maj = 0

    for fault in faults:
        if fault['type'] == 'cow':
            cow += 1
        elif fault['type'] == 'min':
            min += 1
        elif fault['type'] == 'maj':
            maj += 1

    return cow, min, maj


def serialize_memo_by_pid(pid, memo, output='output.csv'):
    filename = f'{pid}_{output}'
    open(filename, 'w+').close()

    with (open(filename, 'a+') as f):
        for _, frame in memo.items():
            line = f"{frame['pid']},{frame['cpus']},{frame['cow']},{frame['min']} \
                    ,{frame['maj']},{frame['lineno']},{frame['filename']}\n"
            f.write(line)


def handle_report(args):
    # 1. read trace json file
    trace = load_trace(args.input)
    frames_dict = group_frames_by_pid(trace['frames'])
    faults_dict = group_faults_by_pid(trace['faults'])
    for proc in trace['procs']['rels']:
        pid = proc['pid']
        faults = faults_dict[pid]
        memo = {}

        fork_time = proc['timestamp']
        startup_faults = get_data_before(faults, fork_time)
        memo['startup'] = {}
        memo['startup']['pid'] = pid
        memo['startup']['cpus'] = get_cpus(startup_faults)
        memo['startup']['lineno'] = -1
        memo['startup']['filename'] = ''
        memo['startup']['cow'], memo['startup']['min'], memo['startup']['maj'] \
            = count_faults_by_types(startup_faults)
        faults = faults[len(startup_faults):]

        frames = frames_dict[pid]
        skip_len = 0
        curr_fid = -1
        for frame in frames:
            key = f"{frame['lineno']}-{frame['filename']}"
            if frame['fid'] != curr_fid:
                curr_fid = frame['fid']
                faults = faults_dict[pid][skip_len:]
            line_faults = get_data_before(faults, frame['timestamp'])
            skip_len = len(line_faults)
            if key not in memo:
                memo[key] = {}
                memo[key]['pid'] = pid
                memo[key]['cpus'] = get_cpus(line_faults)
                memo[key]['lineno'] = frame['lineno']
                memo[key]['filename'] = frame['filename']
                memo[key]['cow'], memo[key]['min'], memo[key]['maj'] \
                    = count_faults_by_types(line_faults)
            else:
                memo[key]['cpus'].union(get_cpus(line_faults))
                cow, min, maj = count_faults_by_types(line_faults)
                memo[key]['cow'] += cow
                memo[key]['min'] = min
                memo[key]['maj'] = maj

        faults = faults[skip_len:]
        memo['teardown'] = {}
        memo['teardown']['pid'] = pid
        memo['teardown']['cpus'] = get_cpus(faults)
        memo['teardown']['lineno'] = -1
        memo['teardown']['filename'] = ''
        memo['teardown']['cow'], memo['teardown']['min'], memo['teardown']['maj'] \
            = count_faults_by_types(faults)

        memo = sorted(memo.items(), key=lambda x: x[1]['cow'])
        serialize_memo_by_pid(pid, memo)

    # 2. convert json data into objects
    # 3. do data analysis (based on timestamps in frames)
    #    3.0 save pid, lineno, code, filename (static values)
    #    3.1 count fault records (0x6 and 0x7) right after fork
    #    3.2 remove these records (for faster search)
    #    3.3 count cumulative fault records for each line of code
    #    3.4 TODO: determine arena range through realloc traces
    #    3.5 TODO: count fault records within the arenas for each line of code
    # 4. write data to file
    # 5. display in gui
    trace_file = args.input
