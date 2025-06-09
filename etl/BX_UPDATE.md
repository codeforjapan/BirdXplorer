# ETLの柔軟性向上

## 現状の整理

### ETLで取れるもの

- Community Noteそのもののデータをそのまま一時保存（SQLiteをつかっているが、Postgresqlにいれる方針）
- Community Noteに紐づくPostのデータをX APIをつかって保存（Postgresqlに保存）
- Community Noteのデータを素材に、LLMで言語の推論
- Community Noteのデータを素材に、LLMでトピックの推論
- BirdXplorer API が必要とするデータモデルに変換する

### ETLの手順

現在実装されているETLの手順は以下の通りです：

#### 1. Community Notesデータの取得
- Twitter公式のBirdwatch公開データから日次でCommunity Notesデータを取得
- データソース: `https://ton.twimg.com/birdwatch-public-data/{日付}/notes/notes-00000.tsv`
- 設定可能な日数分遡ってデータを取得（[`COMMUNITY_NOTE_DAYS_AGO`](etl/src/birdxplorer_etl/settings.py:18)で制御）
- 重複チェックを行い、新しいノートのみをSQLiteに保存
- 同時にNote Status Historyデータも取得・保存

#### 2. 関連Postデータの取得
- Community Noteに紐づくTwitter投稿をX APIで取得
- 対象期間は設定で制御（[`TARGET_TWITTER_POST_START_UNIX_MILLISECOND`](etl/src/birdxplorer_etl/settings.py:12-15)）
- 投稿データ、ユーザーデータ、メディアデータ、埋め込みURLデータをPostgreSQLに保存
- 重複チェックにより既存データの再取得を回避

#### 3. データ変換とCSV生成
- **Note変換**: SQLiteからNoteデータを取得し、AIサービスで言語検出を実行してCSV出力
- **Post変換**: PostgreSQLからPostデータを取得してCSV形式に変換
- **User変換**: PostgreSQLからUserデータを取得してCSV形式に変換
- **Media変換**: メディアデータとPost-Media関連付けデータをCSV出力
- **Link変換**: 埋め込みURLデータとPost-Link関連付けデータをCSV出力

#### 4. AIによる高度な変換
- **言語検出**: [`ai_service.detect_language()`](etl/src/birdxplorer_etl/transform.py:75)でNoteの言語を推論
- **トピック推論**: [`ai_service.detect_topic()`](etl/src/birdxplorer_etl/transform.py:310)でNoteのトピックを分類
- トピックマスターデータは[`topic_seed.csv`](etl/seed/topic_seed.csv)から生成

**出力CSVファイル:**
- `note.csv` - ノートデータ（言語情報付き）
- `post.csv` - 投稿データ
- `user.csv` - ユーザーデータ
- `media.csv` - メディアデータ
- `post_media_association.csv` - 投稿-メディア関連付け
- `post_link.csv` - リンクデータ
- `post_link_association.csv` - 投稿-リンク関連付け
- `topic.csv` - トピックマスターデータ
- `note_topic_association.csv` - ノート-トピック関連付け

#### 4. Load（読み込み）フェーズ ([`load.py`](etl/src/birdxplorer_etl/load.py:9))

**S3への出力:**
- 変換されたCSVファイルをAWS S3バケットにアップロード
- タイムスタンプ付きのプレフィックスで整理
- アップロード対象は全9種類のCSVファイル

## 新しくいれるべきもの

### Post取得の効率化

XのPostデータを取得することはコストがかかるので必要なものを優先的に取得するなどが望まれる。例えば、CommunityNoteのデータをもとにAIや条件で先に前処理をしてメタデータをつけて、特定のCommunityNoteのみを対象にしてPostデータを取るなど。

#### 可能性のあるパターン

- CommunityNoteのデータから言語を先に推定し、日本語のみを対象にしてPostデータを取得
- CommunityNoteのデータからキーワードでフィルタし、該当するものを対象にしてPostデータを取得
  - 派生パターンとしてはCommunityNoteの条件（HELPFULのみや、日時期間の指定など）によってフィルタし、該当するものを対象にする
- CommunityNoteのデータから特定のトピックに関連するかをAIで推論し、該当するものを対象にしてPostデータを取得
- 以上のパターンを組み合わせてできるようにすることも重要

### Community Noteが紐づいている以外の条件でもPostを取得する

CommunityNoteがついているかかかわらず、特定の条件を満たすPostデータを取得できるようにする。
- ProプランのサーチAPIでの条件検索
- 外部からのデータインポート（協力チームからの提供データをインポートすることを想定。データモデルはBirdXplorerに準拠させるためにコンバーターは別途必要）

### 元データの充実

現状BirdXplorer APIのためにETLがあるという位置づけで機能開発されているものを、それ以外の需要にも対応するために、取れるデータはアーカイブとしてすべて取る。

- 取れるものはすべて取る方針
- X APIのフルアーカイブをつくる（関連するもののみ）