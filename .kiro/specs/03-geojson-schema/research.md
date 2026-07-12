# Research & Design Decisions

## Summary
- **Feature**: `03-geojson-schema`
- **Discovery Scope**: New Feature
- **Key Findings**:
  - 道の駅公式サイト(michi-no-eki.jp)は詳細ページのGoogle Maps埋め込みURLから緯度経度を取得可能。付加情報は電話・営業時間・駐車場・18種の施設設備フラグ等
  - NEXCO西日本(w-holdings.co.jp)は`/sapa/json/map-search.json`で緯度経度+約40種のサービスフラグを一括取得可能(310件)。NEXCO中日本もGoogle Mapsリンクから座標取得可能
  - NEXCO東日本(driveplaza.com)は詳細ページ・地図ページとも座標データを持たない(地図は画像マップ)。座標の代替取得手段の検討が必要
  - 施設設備の語彙はサイトごとに異なる(道の駅18種 vs NEXCO西約40種)ため、固定ブール項目ではなく可変の文字列配列としてスキーマ定義するのが妥当

## Research Log

### 取得可能な付加情報の調査(道の駅)

- **Context**: Requirement 2の「付加情報」の具体項目を、スクレイピング対象サイトで実際に取得可能な範囲に基づいて確定するため
- **Sources Consulted**: [道の駅公式(全国「道の駅」連絡会)](https://www.michi-no-eki.jp/) 詳細ページ(例: `/stations/views/18786` 道の駅「三笠」)の実HTML
- **Findings**:
  - 詳細ページURL形式: `https://www.michi-no-eki.jp/stations/views/{駅ID}`
  - 取得可能項目(`<dt>`ラベルより): 道の駅名 / 所在地(郵便番号+住所) / TEL / 駐車場(大型・普通車・身障者用の台数) / 営業時間 / ホームページ(最大2件) / マップコード
  - 施設設備は18種のアイコンフラグ(`facility01`〜`facility18`、`_off`サフィックスで有無を判別): ATM、ベビーベッド、レストラン、軽食・喫茶、宿泊施設、温泉施設、キャンプ場等、公園、展望台、美術館・博物館、ガソリンスタンド、EV充電施設、無線LAN、シャワー、体験施設、観光案内、身障者トイレ、ショップ
  - その他: 登録回(例: 第1回(1993.4)登録)、駅からのお知らせ、写真
  - **緯度経度**: ページ本文には非掲載だが、Google Maps埋め込みURL(`google.com/maps/embed/v1/place?q={緯度},{経度}`)に含まれる(例: `q=43.2466006,141.8045499`)
  - 検索ページは都道府県コードでフィルタ可能: `/stations/search/{都道府県コード}/all/all`
- **Implications**: 名称・住所・電話・営業時間・駐車場・施設設備・ホームページ・マップコード・緯度経度はすべて単一サイトから取得可能。休館日は独立項目として存在しない(営業時間欄に混在)

### 取得可能な付加情報の調査(SA/PA)

- **Context**: SA/PAはNEXCO 3社でサイトが分かれており、取得可能項目と座標の有無がサイトごとに異なるため
- **Sources Consulted**: [ドラぷら(NEXCO東日本)](https://www.driveplaza.com/sapa/)、[NEXCO中日本 SA/PAサイト](https://sapa.c-nexco.co.jp/)、[NEXCO西日本 SA・PA情報サイト(遊・悠・WesT)](https://www.w-holdings.co.jp/) の実HTML/JSON
- **Findings**:
  - **NEXCO東日本(driveplaza.com)**: 詳細ページURL形式 `/sapa/{路線ID}/{施設ID}/{方向}/`(例: Pasar蓮田上り `/sapa/1040/1040021/1/`)。取得可能項目: 名称、路線名、上り/下り、住所(郵便番号付き)、駐車台数(大型/小型)、トイレ数(男女別)、店舗一覧(店舗ごとの営業時間付き)、給油所(ブランド・営業時間)、EV充電、11カテゴリの施設アイコン。**緯度経度はHTML内に存在せず**、地図検索ページ(`/dp/SAPAMap`)も画像マップ(`usemap`)のためデータ取得不可
  - **NEXCO中日本(sapa.c-nexco.co.jp)**: 詳細ページURL形式 `/sapa?sapainfoid={ID}`(例: 牧之原SA下り `?sapainfoid=36`)。Google Mapsへのリンク(`/maps/place/...@{緯度},{経度},17z/`)から**座標取得可能**。検索条件にWi-Fi・ベビー施設・ドッグラン・EV充電等のフラグあり
  - **NEXCO西日本(w-holdings.co.jp)**: `https://www.w-holdings.co.jp/sapa/json/map-search.json` が全310施設のJSONを返す。項目: `id` / `latitude` / `longitude` / `sa_pa`(正式名称) / `sa_pa_short` / `road_name`(例: 「E3A 南九州西回り自動車道」) / `up_down_line` / `field`(方面) / `url`(詳細ページ) / `mujin_flag`(無人) / `service_*` 約40種のブールフラグ(restaurant, snack, takeout, cafe, bakery, convenience, gas, ev_charge, highway_hotel, coin_shower, coin_laundry, baby_corner, kids_corner, atm, highway_stamp, dog_run, pet_cafe, highway_oasis, smart_ic, wi-fi 等)。住所はJSONに含まれず詳細ページ側
  - 旧ドメイン `sapa.w-nexco.co.jp` はDNS解決不可(サイトはw-holdings.co.jpへ移行済み)
- **Implications**: SA/PAは「路線名」「上り/下り」「方面」という道の駅にない固有属性を持つ。施設サービスの語彙・粒度が3社で異なる。NEXCO東日本管内のみ座標の直接取得ができない

### 座標が取得できないソース(NEXCO東日本)への対応

- **Context**: GeoJSONは`geometry.coordinates`が必須のため、座標を持たないソースの扱いを決める必要がある
- **Sources Consulted**: driveplaza.comの詳細ページHTML・`/dp/SAPAMap`・関連JS
- **Findings**: ページ内に緯度経度・地図タイル・座標APIのいずれも存在しない
- **Implications**: 05/06のspecで対応方針(住所ジオコーディング、他社サイトとの突合、別データソースの併用等)を決める必要がある。本spec(スキーマ)としては「座標は必須。取得できないFeatureはバリデーションエラーとして出力対象外」という位置づけを維持すればよい

### 既存コードベースのパターン調査(design discovery light)

- **Context**: 設計を既存の`02-common-infra`実装(`src/roadstop_scraper/common/`)のパターンに揃えるため
- **Sources Consulted**: `index_store.py`、`_atomic_io.py`、`rate_limiter.py`、`resume_store.py`、`pyproject.toml`
- **Findings**:
  - データ表現は`@dataclass(frozen=True)`による不変オブジェクト。更新は新インスタンス生成(`upsert_entry`が典型)
  - APIはクラスではなくモジュールレベル関数+`__all__`による公開制御
  - エラーは`ValueError`サブクラスの独自例外(例: `IndexFileCorruptedError`)に正規化し、日本語メッセージで文脈を付与
  - ファイル書き込みは`write_text_atomic`(同一ディレクトリの一時ファイル+`os.replace`)で部分書き込み破損を防止
  - 外部依存は`python_util`(git依存)のみ。バリデーションは`index_store._parse_*`のように手書きの型チェックで実装しており、pydantic等は未導入
  - Python 3.11+、`from __future__ import annotations`、日本語docstring(How観点)
- **Implications**: GeoJSONスキーマも frozen dataclass+モジュール関数+独自例外+`write_text_atomic`再利用で設計するのが一貫する。バリデーションライブラリの新規導入は既存方針と乖離する

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| frozen dataclass+手書き検証(採用) | `common/`と同じ不変dataclassとモジュール関数で型・検証を実装 | 依存追加ゼロ、既存パターンと完全に一貫、検証エラーの粒度を自由に設計できる | 検証ロジックのコード量が増える | `index_store.py`の`_parse_*`と同型のアプローチ |
| pydantic v2 | BaseModelでスキーマ+検証を宣言的に定義 | 検証コードが短い、JSON Schema出力可 | 新規依存追加、既存コードと二流儀になる、frozen dataclassとの混在 | 本プロジェクト規模では過剰と判断 |
| jsonschema | JSON Schema文書+汎用バリデータ | スキーマを言語非依存の文書として公開できる | エラーメッセージが機械的で「対象Feature・項目名の特定」(5.2)の実装が回りくどい、依存追加 | スキーマ文書公開の要求が生じたら再検討 |

## Design Decisions

### Decision: バリデーションは標準ライブラリのみ(frozen dataclass+手書き検証)で実装する

- **Context**: Requirement 5の出力前バリデーションを実現する手段として、pydantic/jsonschema等の導入か既存パターン踏襲かを選ぶ必要がある
- **Alternatives Considered**:
  1. pydantic v2導入 — 宣言的だが新規依存+既存コードとの二流儀化
  2. jsonschema導入 — スキーマ文書は得られるがエラー特定(5.2)の実装が回りくどい
  3. `common/`と同じfrozen dataclass+手書き検証 — 依存追加なし・一貫性維持
- **Selected Approach**: 案3。型はfrozen dataclassで表現し、検証はモジュール関数が違反リスト(対象Feature・項目名・理由)を収集して返す
- **Rationale**: 既存の`index_store.py`が同方式で成立しており、検証項目数(必須項目・座標範囲・命名規則・列挙値)は手書きで十分管理できる規模のため
- **Trade-offs**: 検証コードは自前保守になるが、依存を増やさず`tech.md`のスタック(python_utilのみ)を維持できる
- **Follow-up**: 検証項目が大幅に増えた場合はjsonschema化を再検討

### Decision: GeoJSON出力は「検証ゲート付きライタ」として本specが提供する

- **Context**: Requirement 5.5「検証エラーが1件以上あれば出力を中断」を、利用側(05/06)の実装規律に頼らず構造的に保証したい
- **Alternatives Considered**:
  1. 検証関数のみ提供し、ファイル書き込みは05/06が実装 — 検証を飛ばした書き込みが可能になってしまう
  2. 検証+アトミック書き込みを一体化したライタ関数を本specが提供
- **Selected Approach**: 案2。`write_geojson()`が検証→違反あれば例外(書き込みなし)→合格時のみ`write_text_atomic`で書き込む、という唯一の出力経路になる
- **Rationale**: 「スキーマに適合しないデータを`geo-json/`配下へ永続化しない」という不変条件をAPI境界で強制できる。`02-common-infra`のアトミック書き込みも再利用できる
- **Trade-offs**: 05/06はファイル書き込みの自由度を失うが、それ自体が狙い
- **Follow-up**: index.jsonへの登録(`index_store.upsert_entry`)は従来どおり05/06の責務。書き込み成功→index更新の呼び出し順序をtasksで明示する

### Decision: ファイル名とFeature内容の整合検証は行わない(設計レビューでの決定)

- **Context**: 設計レビューで「ファイル名の構成要素(都道府県・種別)とFeature内容のクロスチェック」を追加する案が提示された
- **Alternatives Considered**:
  1. writerでファイル名とFeature内容の一致を検証する — ファイル名に内容の契約を持たせることになる
  2. 整合検証を行わず、ファイル名は分割の単位としてのみ扱う
- **Selected Approach**: 案2。ファイル名は命名規則(パターン適合)のみ検証し、内容との整合は検証しない
- **Rationale**: ファイル名に情報を持たせると、将来ファイルが肥大化した際の再分割(例: 北海道の複数ファイル化)などの拡張性を犠牲にする。ファイルはあくまで分割の単位であり、都道府県・種別の正はFeatureの`properties`(`pref_code`/`kind`)側にある(ユーザー判断)
- **Trade-offs**: 内容と食い違う名前のファイルを機械的には検出しない。消費側は`properties`を正として扱う必要がある
- **Follow-up**: 分割規則を変更する場合は命名規則パターン(Requirement 4)の改訂として扱う

### Decision: `direction`(上り/下り)は日本語2値の列挙型で正規化する(設計レビューでの決定)

- **Context**: 設計レビューで`direction: str | None`の自由文字列は情報源の表記ゆれ(「up」「上り線」等)が混入すると指摘された
- **Alternatives Considered**:
  1. 英語2値(`up`/`down`) — NEXCO西日本のJSON表記と一致
  2. 日本語2値(`上り`/`下り`) — 消費側(道の駅アプリ等)にとって表示にそのまま使える
- **Selected Approach**: 案2。`Direction`列挙型(`上り`/`下り`)として定義し、生の文字列は受理しない。情報源表記から列挙値への正規化は05/06のマッピング責務とする(ユーザー判断: 生データをそのまま使わず、デフォルトは日本語が望ましい)
- **Trade-offs**: 05/06に正規化マッピングの実装が必要になるが、スキーマとしての一貫性を優先する
- **Follow-up**: 05/06のtasksに情報源表記→`Direction`のマッピング作業を含める

### Decision: 付加情報は固定項目+可変の施設設備リストで表現する

- **Context**: 道の駅(18種)とNEXCO各社(約40種/11カテゴリ)で施設設備の語彙・粒度が異なり、全項目を固定ブールで定義すると欠損と語彙差の吸収が困難
- **Alternatives Considered**:
  1. 全施設設備を固定ブール項目として定義 — 語彙統一の負担が大きく、ソース追加時にスキーマ変更が必要
  2. 共通で取得できる項目のみ固定項目とし、施設設備は文字列配列(タグリスト)として保持
- **Selected Approach**: 案2。電話番号・営業時間・駐車場台数・ホームページ等は名前付き任意項目、施設設備は文字列配列
- **Rationale**: 両ドメインで実際に取得可能な項目を検証した結果、共通化できるのは電話・営業時間・駐車場・URL程度で、施設設備はソース依存の語彙になるため
- **Trade-offs**: 消費側でタグ文字列の表記ゆれを吸収する必要がある(将来の正規化余地を残す)
- **Follow-up**: requirements.md Requirement 2への具体項目の反映(ユーザーレビュー後)

## Risks & Mitigations

- NEXCO東日本管内のSA/PA座標が対象サイトから取得不可 — 06-sapa-scrapingで代替手段(住所ジオコーディング等)を検討。本specでは座標必須のバリデーションを維持
- 対象サイトのHTML構造変更・ドメイン移行(w-nexcoの例あり) — 情報源URL(`source_url`)をFeatureに保持し、再取得・検証を容易にする
- SA/PAの営業時間は店舗単位でしか存在しない — 施設全体の営業時間は自由記述または省略可能とする

## References

- [道の駅公式ホームページ 全国「道の駅」連絡会](https://www.michi-no-eki.jp/) — 道の駅スクレイピング対象の第一候補
- [国土交通省 道の駅案内 一覧](https://www.mlit.go.jp/road/Michi-no-Eki/list.html) — 登録駅の網羅性確認用
- [ドラぷら(NEXCO東日本) サービスエリア](https://www.driveplaza.com/sapa/) — 東日本管内SA/PA(座標なし)
- [NEXCO中日本 サービスエリア検索](https://sapa.c-nexco.co.jp/) — 中日本管内SA/PA(Google Mapsリンクに座標)
- [NEXCO西日本 SA・PA情報サイト](https://www.w-holdings.co.jp/) — 西日本管内SA/PA(`/sapa/json/map-search.json`で座標+サービスフラグ)
