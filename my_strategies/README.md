# my_strategies — 你自己的策略放这里

每个 `.py` 文件里的 `Policy` 子类（带 `name` 属性）都会被自动加载，
可以直接用于 `--policies`：

```bash
python3 -m mahjong_mc --games 50000 --policies mine,greedy,random,random --workers 8
```

不需要 `--policy-file`，也不需要改包内代码。改完直接跑。

模板（复制 `mine.py` 改名后编辑，改文件里的 `name` 属性即可）：

```python
from mahjong_mc.policies import Policy, register
from mahjong_mc.rules import shanten, ukeire

@register
class MyStrategy(Policy):
    name = "mine"          # ← 这就是 --policies 里用的名字

    def choose_discard(self, view):
        # view.hand / view.counts / view.total_counts / view.melds
        # view.discards / view.melds_all / view.unseen_counts
        # view.wall_left / view.dealer / view.points / view.riichi
        # view.can_riichi / view.dora_count / view.last_drawn
        ...
        return tile_id     # 必须在 view.hand 里

    def decide_call(self, view, tile, options):   # 碰/吃/大明杠/加杠
        # options: [(kind, trio, meld_kind), ...]
        return None       # 或返回其中一个 option

    def decide_riichi(self, view):                # 立直
        return view.can_riichi

    def decide_kan(self, view, tile, options):    # 暗杠/加杠（自摸时）
        return None
```

规则：日麻（立直/宝牌/杠/番符算点）。完整说明见 README。
