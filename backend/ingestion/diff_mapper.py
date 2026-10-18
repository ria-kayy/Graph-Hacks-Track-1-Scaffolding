"""Map zero-context hunks to symbols in BOTH revisions, including deletions."""
import re

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def changed_ranges(diff):
    return [(int(a), int(b or 1), int(c), int(d or 1)) for a, b, c, d in HUNK.findall(diff)]


def overlap(start, count, symbol):
    return count > 0 and start <= symbol["end_line"] and start + count - 1 >= symbol["start_line"]


def map_symbols(diff, before, after):
    found = {}
    for old_start, old_count, new_start, new_count in changed_ranges(diff):
        for symbols, start, count in ((before, old_start, old_count), (after, new_start, new_count)):
            for symbol in symbols:
                if overlap(start, count, symbol):
                    data = found.setdefault(symbol["id"], {"symbol": symbol, "lines_added": 0, "lines_deleted": 0})
                    if symbols is after:
                        data["lines_added"] += max(0, min(symbol["end_line"], new_start+new_count-1) - max(symbol["start_line"], new_start)+1)
                    else:
                        data["lines_deleted"] += max(0, min(symbol["end_line"], old_start+old_count-1) - max(symbol["start_line"], old_start)+1)
    return list(found.values())
