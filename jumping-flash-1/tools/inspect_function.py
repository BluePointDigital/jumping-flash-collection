"""Read one recovered function or its callers without shell-escaped MIPS registers."""
from pathlib import Path
import argparse
import re

parser=argparse.ArgumentParser();parser.add_argument('address',nargs='*');parser.add_argument('--callers',action='store_true')
parser.add_argument('--player-writes',action='store_true');parser.add_argument('--image',default='JM1/MAIN.PEX');args=parser.parse_args()
source=Path(__file__).resolve().parents[1]/'.workbench/analysis/original'/args.image/'disassembly.txt'
blocks=source.read_text().split('/* ------------------------------------------------------------ */')
for block in blocks:
    header=re.search(r'/\* func_([0-9A-F]{8}).*',block)
    if not header:continue
    if args.player_writes:
        if header[1].startswith('800D') and re.search(r'(sw|sh).* (140|144|164)\(\$s0\)',block):print(header[0])
    elif args.callers:
        if any(re.search(r'jal\s+0x'+address,block) for address in args.address):print(header[0])
    elif header[1] in args.address:print(block)
