# mcp-maya

起動中の Autodesk Maya を、commandPort 経由で操作する MCP サーバーです。
Claude などの MCP クライアントから、Maya 内で Python を実行したり、シーンを調べたり、ビューポートを画像で確認したりできます。

- Maya 側にプラグインのインストールは不要です（commandPort を開くだけ）。
- Maya と同じ PC で動かします。コードと結果は一時ファイルで受け渡すため、別マシンの Maya には接続できません。
- 対応: Maya 2022 以降（Python 3）。動作確認は Maya 2025。

## セットアップ

### 1. 依存パッケージを入れる

[uv](https://docs.astral.sh/uv/) が必要です。

```bash
uv sync
```

### 2. Maya で commandPort を開く

Maya の Script Editor（Python タブ）で [maya/open_port.py](maya/open_port.py) の内容を実行します。最小限なら次の2行です。

```python
import maya.cmds as cmds
cmds.commandPort(name="127.0.0.1:7001", sourceType="python")
```

閉じるときは次を実行します。

```python
cmds.commandPort(name="127.0.0.1:7001", close=True)
```

> **注意**: ポートを開いている間は、この PC 上のどのプログラムからでも Maya にコードを実行させられます。`127.0.0.1` に限定しているので他の PC からは届きませんが、使い終わったら閉じてください。

### 3. MCP クライアントに登録する

Claude Code の場合は、プロジェクト直下の `.mcp.json` に追加します（パスは自分の環境に合わせてください）。

```json
{
  "mcpServers": {
    "maya": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\path\\to\\mcp-maya", "mcp-maya"]
    }
  }
}
```

このリポジトリ自体を Claude Code で開く場合は、同梱の [.mcp.json](.mcp.json) がそのまま使われます。

Claude Desktop の場合は `claude_desktop_config.json` の `mcpServers` に同じ内容を追加します。

## ツール

| ツール | 内容 |
|---|---|
| `maya_status` | 接続確認。Maya のバージョンと開いているシーンを返す |
| `execute_python` | Maya 内で Python を実行し、print 出力と最後の式の値を返す |
| `scene_summary` | シーンの概要（ファイル、単位、アップ軸、フレーム範囲、ノード数、選択） |
| `list_nodes` | ノードタイプや名前パターンでノードを列挙 |
| `node_info` | 1ノードのタイプ、階層、チャンネル値、接続（ジョイントは jointOrient も） |
| `capture_viewport` | アクティブなビューポートのスクリーンショット |

`execute_python` の挙動:

- Script Editor と同じ `__main__` 名前空間で実行するので、変数や import は呼び出しをまたいで残ります。
- 1回の呼び出しが Maya 上で1つの undo になります（`undo_chunk=False` で無効化）。
- Maya のメインスレッドで実行するため、実行中は Maya の操作ができません。
- `timeout_s` はツール側が待つ時間です。タイムアウトしても Maya 側の処理は止まりません。
- `cmds.warning()` など Maya 自身が出すメッセージは取得できません（Script Editor には表示されます）。

## 設定（環境変数）

| 変数 | 既定値 | 内容 |
|---|---|---|
| `MAYA_HOST` | `127.0.0.1` | commandPort のホスト |
| `MAYA_PORT` | `7001` | commandPort のポート |
| `MAYA_TIMEOUT` | `120` | 応答を待つ秒数の既定値 |
| `MAYA_SOURCE_TYPE` | `python` | commandPort を MEL で開いている場合は `mel` |

## 仕組み

commandPort には一度に送れるサイズの上限（既定 4096 バイト）があるため、コード本体は送りません。

1. サーバーがリクエスト（コードと引数）を一時ファイルに書く。
2. commandPort へは「[bridge.py](src/mcp_maya/bridge.py) を実行せよ」という短い1行だけを送る。
3. bridge.py が Maya 内でコードを実行し、出力・戻り値・トレースバックを結果ファイルに書く。
4. サーバーが結果ファイルを読んで返す。

組み込みツールの Maya 側の実装は [maya_tools.py](src/mcp_maya/maya_tools.py) にあります。

## 開発

```bash
uv run pytest
```

テストは Maya なしで動きます（commandPort と `maya.cmds` を偽物に差し替えて、クライアントと bridge の往復を確認します）。
