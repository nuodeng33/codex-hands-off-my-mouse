"""Diff adjacent comparable UIA observations using provider runtime IDs."""
from collections import Counter

class TreeHistory:
    def __init__(self):
        self.last = None

    def key(self, args):
        return (args['hwnd'], args['pid'], args.get('root_name'), args.get('root_automation_id'),
                args.get('depth', 16), args.get('limit', 200))

    def prepare(self, args):
        if 'diff_from' not in args:
            return
        if not self.last or (args['diff_from'], self.key(args)) != self.last[:2]:
            raise ValueError('diff_from requires the immediately preceding observation of the same window, selector and limits')

    def update(self, args, result):
        previous = self.last
        nodes = result['nodes']
        raw_ids = [n.pop('runtime_key', None) for n in nodes]
        counts = Counter(raw_ids)
        index = {key: node for key, node in zip(raw_ids, nodes) if key and counts[key] == 1}
        uncertain = result['truncated'] or len(index) != len(nodes)
        self.last = (result['observation_id'], self.key(args), index, uncertain)
        if 'diff_from' not in args:
            return result
        old, incomplete = previous[2:]
        incomplete = incomplete or uncertain
        def fields(n):
            return {k:v for k,v in n.items() if k != 'id'}
        added = [n for k,n in index.items() if k not in old]
        changed = [n for k,n in index.items() if k in old and fields(n) != fields(old[k])]
        removed = [] if incomplete else [fields(n) for k,n in old.items() if k not in index]
        # With a truncated or ambiguous baseline, presence is observed, novelty is unknown.
        newly_visible = added if previous[3] else []
        added = [] if previous[3] else added
        result['nodes'] = added + newly_visible + changed
        result['diff'] = {'added':added,'changed':changed,'removed':removed,'newly_visible':newly_visible,
                          'unobserved':bool(incomplete),'unchanged_count':len(index.keys() & old.keys())-len(changed)}
        return result

