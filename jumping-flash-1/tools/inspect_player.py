"""Find static actor-address candidates; live input/trace checks must establish meaning."""
from pathlib import Path
from collections import Counter, defaultdict
import re

ROOT = Path(__file__).resolve().parents[1]


def candidates():
    source = ROOT/'.workbench/analysis/original/JM1/MAIN.PEX/disassembly.txt'
    lines = source.read_text().splitlines()
    counts, functions = Counter(), defaultdict(set)
    function = ''
    for index, line in enumerate(lines):
        match = re.search(r'/\* (func_[0-9A-F]+) ', line)
        if match:
            function = match[1]
        high = re.search(r'lui\s+\$(\w+), 0x(801[0-9A-F])', line)
        if not high:
            continue
        register, value = high[1], int(high[2], 16) << 16
        for following in lines[index+1:index+7]:
            low = re.search(r'addiu\s+\$\w+, \$'+register+r', (-?\d+)\s*$', following)
            if low:
                address = value+int(low[1])
                if 0x80100000 <= address < 0x80200000:
                    counts[address] += 1
                    functions[address].add(function)
                break
    for address, count in counts.most_common(24):
        print(f'{address:08X} refs={count} functions={", ".join(sorted(functions[address]))}')


if __name__ == '__main__':
    candidates()
