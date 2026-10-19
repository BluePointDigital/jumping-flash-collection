"""Private static-audit guard batching with lazy per-recipe identity sets."""


def _within_bounds(ranges, bounds):
    return all(any(lo <= (start & 0x1FFFFFFF) and
                   (start & 0x1FFFFFFF) + length <= hi
                   for lo, hi in bounds)
               for start, length in ranges)


def _guard_key(item):
    _entry, crc, ranges = item
    return (crc & 0xFFFFFFFF, tuple(tuple(span) for span in ranges))


class RecipeCompatibleGroups:
    """Lazy exact-identity view backed by shared groups of input indexes."""
    __slots__ = ('_ids', '_groups')

    def __init__(self, ids, groups):
        self._ids = ids
        self._groups = groups

    def materialize(self):
        result = set()
        for group in self._groups:
            ranges = group['ranges']
            for index in group['indexes']:
                entry, crc, _ = self._ids[index]
                result.add((entry, crc, ranges))
        return result


def batched_static_audit(ids, recipes, compiler):
    """Return first witnesses and lazy per-recipe compatible identity views.

    One representative per exact (masked CRC, ordered ranges) group is checked
    against each recipe. Group/index references are shared across recipe views;
    callers materialize only the current image's compatible identity set.
    """
    ids = ids if isinstance(ids, list) else list(ids)
    groups = {}
    for index, item in enumerate(ids):
        key = _guard_key(item)
        group = groups.get(key)
        if group is None:
            group = {'indexes': [], 'ranges': key[1]}
            groups[key] = group
        group['indexes'].append(index)

    matched = [None] * len(ids)
    compatible_by_recipe = []
    for name, load, data, bounds in recipes:
        accepted = []
        for group in groups.values():
            representative = ids[group['indexes'][0]]
            if not _within_bounds(representative[2], bounds):
                continue
            if not compiler.current_variant_func_ids(
                    [representative], data, load, len(data)):
                continue
            accepted.append(group)
            for index in group['indexes']:
                if matched[index] is None:
                    matched[index] = name
        compatible_by_recipe.append(RecipeCompatibleGroups(ids, accepted))
    return matched, compatible_by_recipe
