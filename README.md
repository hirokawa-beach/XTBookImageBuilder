# XTBook 日本語Wikipedia画像辞書ビルダー

日本語Wikipediaの記事で使われている画像から、再配布可能と機械的に確認できたものだけを収録し、XTBook用の画像辞書を生成するツールです。

公式Wikimedia DumpとMediaWiki Action APIを利用します。Wikipediaの記事ページを巡回するWebクローラではありません。ライセンスが不明確な画像や再配布条件に問題がある画像は取得しません。

生成ファイル：`jawikiimg-YYYYMMDD.xtbdict`

## 目次

- [主な機能](#主な機能)
- [動作環境](#動作環境)
- [インストール](#インストール)
- [User-Agentの設定](#user-agentの設定)
- [MkImageComplex-binの準備](#mkimagecomplex-binの準備)
- [クイックスタート](#クイックスタート)
- [GUI](#gui)
- [CLI](#cli)
- [中断と再開](#中断と再開)
- [ライセンス判定](#ライセンス判定)
- [画像変換](#画像変換)
- [成果物](#成果物)
- [テスト](#テスト)
- [実装上の安全対策](#実装上の安全対策)
- [ライセンス](#ライセンス)
- [参考資料](#参考資料)

## 主な機能

- 日本語Wikipediaの公式`imagelinks.sql.gz`と`linktarget.sql.gz`から、標準記事で使われている画像を抽出
- Public Domain、CC0、CC BY、CC BY-SAだけを自動収録
- ライセンス名が不明または未対応の画像は`REVIEW`へ分類
- ライセンス名にNC、ND、Fair useなどが含まれる画像は`DENY`へ分類
- ライセンス判定後にのみWikimediaのサムネイルをダウンロード
- XTBook向けにJPEG quality 85、最大800×480へ変換
- SQLiteによる進捗保存と中断・再開
- CLIとTkinter GUIの両方を提供
- `ATTRIBUTION.html`、`licenses.csv`、判定レポートを自動生成
- Raspberry Piを含むLinux ARM64向け`MkImageComplex-bin`ビルドスクリプトを同梱

## 動作環境

- Python 3.11以降
- `requests`
- Pillow
- GUIを使う場合はTkinter
- 辞書生成時は、実行環境で動作する`MkImageComplex-bin`

Python部分は特定のマシンに依存しない構成です。最終的なImageComplex辞書の生成には、利用するOS・CPU向けの`MkImageComplex-bin`が必要です。

全件処理ではDump、ダウンロード画像、変換済みJPEG、完成辞書を同時に保存します。必要な容量は対象時点の画像数によって変わるため、十分な空き容量があるストレージを利用してください。

## インストール

リポジトリを取得します。

```sh
git clone https://github.com/hirokawa-beach/XTBookImageBuilder.git
cd XTBookImageBuilder
```

仮想環境を作成してインストールします。

### Linux / macOS

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp config.toml.example config.toml
```

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
Copy-Item config.toml.example config.toml
```

TkinterがPythonに含まれていないLinux環境では、ディストリビューションのpackage managerから追加してください。Debian系の例：

```sh
sudo apt install python3-tk
```

## User-Agentの設定

ネットワーク処理を始める前に、`config.toml`の`user_agent`を変更してください。Wikimediaの方針により、実在するメールアドレス、連絡用Webページ、またはwiki userを含む専用User-Agentが必要です。

```toml
user_agent = "XTbookImgBuilderBot/0.1 (https://example.org/contact; operator@example.org) requests/2"
```

サンプルの`example.invalid`が残っている場合、ツールはネットワーク処理を開始しません。

既定値はAction APIが同時1・約2 req/s・batch 10、画像取得が最大2並列・合計20 Mbpsです。429では`Retry-After`を尊重し、5xxやtimeoutでは指数backoffを行います。

## MkImageComplex-binの準備

すでに利用可能な`MkImageComplex-bin`がある場合は、`config.toml`へpathを指定します。

```toml
mkimagecomplex_bin = "/path/to/MkImageComplex-bin"
```

PATH上にある場合、またはプロジェクトの`tools/MkImageComplex-bin`に配置した場合は自動検出されます。

### Linux ARM64でビルドする場合

Linux ARM64環境向けの補助スクリプトを用意しています。Raspberry Pi OS 64-bitなどで利用できます。

Debian系では、先にビルド依存関係を導入します。

```sh
sudo apt install git g++ pkg-config libxml2-dev
sh scripts/build_mkimagecomplex_arm64.sh
```

生成先は`tools/MkImageComplex-bin`です。このスクリプトは`watamario15/MkXTBWikiplexus`から固定revisionを取得し、必要なMkImageComplex部分だけをビルドします。

## クイックスタート

最初は100件に制限して、設定と一連の処理を確認してください。

```sh
python -m jawikiimg all --limit 100
```

`--limit 100`は抽出後の画像処理件数を100件に制限します。SQL Dump自体は完全なファイルを取得するため、通信量と保存容量には注意してください。

成功すると、次の場所に辞書が生成されます。

```text
work/output/jawikiimg-YYYYMMDD.xtbdict/
```

同じ作業directoryのまま全件処理へ進む場合：

```sh
python -m jawikiimg all
```

100件テストで完了したmetadata取得、ダウンロード、画像変換は再利用されます。

## GUI

```sh
python -m jawikiimg gui
```

GUIでは次の情報を確認できます。

- Dump日付と発見画像数
- metadata取得進捗
- ALLOW / REVIEW / DENY件数
- ダウンロード・JPEG変換進捗
- API速度・ダウンロード速度
- ステージごとの件数・割合・残り時間の目安
- Dump解析の読取率・走査行数・発見画像数
- ディスク空き容量と現在処理中のファイル
- REVIEW / DENY画像と判定理由・ライセンス・Permission・Restrictions
- REVIEW画像の手動承認、手動DENY、手動判定の解除

開始、一時停止、再開、安全な停止に対応しています。長時間処理はTkinterのmain threadとは別のworker threadで実行されます。

手動承認は対応ライセンスを特定できる`REVIEW`画像に限られます。`DENY`画像や未対応ライセンスは承認できません。承認状態、確認メモ、日時はSQLiteとCSVへ保存され、自動再判定でも上書きされません。手動承認後は処理を再開すると、その画像のダウンロード・変換・辞書収録が行われます。

## CLI

全工程は個別にも実行できます。

```sh
python -m jawikiimg fetch-dumps
python -m jawikiimg extract
python -m jawikiimg metadata
python -m jawikiimg classify
python -m jawikiimg download
python -m jawikiimg convert
python -m jawikiimg build
python -m jawikiimg report
```

特定のDump snapshotを使う場合：

```sh
python -m jawikiimg fetch-dumps --date YYYYMMDD
```

作業directoryを変更する場合は、subcommandより前に`--workdir`を指定します。

```sh
python -m jawikiimg --workdir /path/to/jawikiimg-work all --limit 100
```

CLIでは、処理名、進捗率、処理件数、速度、経過時間、残り時間の目安を表示します。端末上では同じ進捗行を更新するため、長時間処理でもログが埋まりません。

機械処理向けに従来の1行1 JSONが必要な場合は、subcommandより前に`--json-progress`を指定します。

```sh
python -m jawikiimg --json-progress all --limit 100
```

## 中断と再開

進捗は`work/jawikiimg.sqlite3`へ保存されます。

- Dumpは`.part`へ保存され、再実行時にRange requestで再開
- 画像とJPEGは`.part`への書き込み完了後にatomic rename
- metadata、download、convertの完了状態を画像単位で記録
- 完了済みの処理は再実行時にskip
- GUIの「安全な停止」またはCLIの中断後も、同じcommandで再開可能

別snapshotを選択した場合は、異なるDump由来のデータを混在させないよう抽出状態が切り替わります。

## ライセンス判定

自動判定の状態は次の6種類です。

| 状態 | 扱い |
|---|---|
| `ALLOW_PD` | Public Domainとして収録 |
| `ALLOW_CC0` | CC0として収録 |
| `ALLOW_CC_BY` | CC BYとして収録 |
| `ALLOW_CC_BY_SA` | CC BY-SAとして収録 |
| `REVIEW` | 収録せず、人による確認対象 |
| `DENY` | 収録しない |

判定にはWikimedia metadataの`LicenseShortName`だけを使用します。Public Domain、CC0、CC BY、CC BY-SAを含むライセンス名はALLOW、NC・ND・Fair useなどの非自由ライセンス名はDENY、欠損または未対応ライセンス名はREVIEWになります。`Permission`、`Restrictions`、`Copyrighted`、`NonFree`などの他のmetadataは判定を変更せず、確認用としてSQLiteとCSVへ保存します。複数ライセンス名に対応ライセンスが含まれる場合は、その対応ライセンスを選んでALLOWします。

取得した`extmetadata`とAPI responseはSQLiteに保存されるため、後から判定根拠を確認できます。

## 画像変換

収録画像はXTBook互換化のため、次の条件で一括変換されます。

- JPEG
- quality 85
- 最大800×480
- アスペクト比を維持
- 小さい画像は拡大しない
- alpha channelは白背景へ合成

元の拡張子はXTBookのkeyに残ります。

```text
Example.jpg → Example.jpg.jpg
Example.png → Example.png.jpg
Example.svg → Example.svg.jpg
```

## 成果物

辞書bundleには次のファイルが生成されます。

- `Images.db` / `Images.keys` / `Images.indices` / `Titles.txt`
- `Info.plist`（scheme: `jawikiimg`）
- `ATTRIBUTION.html`
- `licenses.csv`
- `report.json`
- `review.csv`
- `errors.csv`

`ATTRIBUTION.html`と`licenses.csv`では、元ファイル名、作者またはAttribution、ライセンス名、ライセンスURL、Wikimedia description URLを確認できます。`review.csv`にも同じ判断材料に加えて、Permission、Restrictions、判定理由を保存します。大量データを扱えるよう、帰属情報とreportは全件をRAMへ載せずstreaming生成します。

## テスト

```sh
python -m unittest discover -v
```

SQL Dump parser、現行・旧schema、ライセンス判定、ファイル名、resize、alpha合成、中断再開、namespace filter、件数制限、Info.plistをテストします。

## 実装上の安全対策

- 同じ`dumpstatus.json`で完了した`imagelinks`と`linktarget`だけを使用
- gzip Dumpをstreaming解析し、全体をRAMへ展開しない
- MySQLの文字列、escape、`NULL`を解析し、単純なカンマ分割をしない
- 現行`il_target_id` schemaと旧`il_to` schemaの両方に対応
- 大量レコードはSQLiteとbounded batchで処理
- ディスク空き容量を監視し、設定値を下回ると停止
- REVIEW / DENY画像をダウンロードしない

## ライセンス

このリポジトリのMITライセンスは、本プロジェクトのPythonコードにのみ適用されます。生成された辞書、収録画像、MkImageComplexおよびその他の第三者成果物には適用されません。それぞれの権利者が定めるライセンスと利用条件に従ってください。

画像のライセンス判定は法的助言ではありません。Wikimedia上のmetadataは後から訂正される可能性があります。辞書を配布する前に、`licenses.csv`、`review.csv`、`errors.csv`および`ATTRIBUTION.html`を確認してください。

## 参考資料

- [Wikimedia Robot policy](https://wikitech.wikimedia.org/wiki/Robot_policy)
- [Wikimedia Foundation API Usage Guidelines](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines/en)
- [Wikimedia Foundation User-Agent Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy/en)
- [MediaWiki Action API: Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo)
- [Japanese Wikipedia official dumps](https://dumps.wikimedia.org/jawiki/)
- [watamario15/xtbook](https://github.com/watamario15/xtbook)
- [watamario15/MkXTBWikiplexus](https://github.com/watamario15/MkXTBWikiplexus)
