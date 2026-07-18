# Gap Analysis

## Summary

- **Feature**: `05-michinoeki-scraping`
- **Discovery Scope**: Brownfield extension — `02-common-infra`・`03-geojson-schema`・`04-scraping-engine`が実装完了済みで、本specはそれらを利用するドメイン層(サイト固有の収集ロジック)を新規実装する
- **Key Findings**:
  - `02`(レート制限・レジューム・index.json・共通ロギング)・`04`(HTTP取得・HTMLパース・URL単位レジューム)は要件1〜7・9のほぼ全面を直接カバーでき、05固有の新規実装はサイト固有の収集ロジックと範囲指定・削除状態管理に集約される
  - 要件8(廃止駅の削除フラグ・1年保持)は、要件定義時に合意した「03のFacilityProperties拡張」だけでは不十分。**既存GeoJSONを読み戻して前回状態とマージする機能が現状どこにも存在しない**(`geojson`パッケージは書き込み専用で読み込みAPIがない)ため、この読み戻し機能の追加場所も設計フェーズで決定が必要
  - 要件1(全国/地方8区分/都道府県の範囲指定)を支える「地方区分↔都道府県対応表」は、`03-geojson-schema`の`prefectures.py`(都道府県コード↔ローマ字/日本語名のみ)にも05パッケージにも存在しない新規テーブルが必要。06-sapa-scrapingでも将来同じ区分が要るため、所有場所(03拡張 or 05専有)は設計判断が必要
  - 対象サイト(michi-no-eki.jp)の一覧ページ・施設設備アイコン(18種)・マップコード表示箇所の正確なCSSセレクタは、03のresearch.mdに大枠の調査結果はあるが実装に足る精度(class名・DOM構造)までは確認されておらず、設計フェーズでの実地調査が必要
  - プロジェクトに実行エントリポイント(CLI・`__main__`・pyproject `scripts`)の前例がなく、範囲指定(全国/地方/都道府県)を伴う実行インタフェースは本specが初めて確立する

## Requirement-to-Asset Map

| Requirement | 既存アセット | 状態 |
|---|---|---|
| 1. 実行対象範囲の指定 | `geojson.prefectures.PREFECTURES`(都道府県対応表) | **Missing**: 地方区分↔都道府県の対応表、範囲指定を受け取る実行インタフェースが存在しない |
| 2. 道の駅一覧の収集 | `scraping.PageFetcher.fetch_text`, `scraping.parser.parse_html`/`HtmlPage` | **Missing**: 対象サイトの一覧/検索ページURL構築・詳細ページURL抽出ロジック(サイト固有、05が新規実装) |
| 3. 道の駅詳細情報の抽出 | `scraping.extract.FieldSpec`/`extract_record`, `HtmlPage.find_*`/`require_*` | **Missing/Constraint**: 緯度経度はGoogle Maps embed URLの属性値からの正規表現抽出が必要で`FieldSpec`の単純セレクタ抽出では賄えない。施設設備18種アイコンの判定ロジックも同様に新規実装が必要 |
| 4. 抽出失敗時のエラーハンドリング | `scraping.errors.StructureChangedError` | **Covered**: 既存の例外型をtry/exceptで捕捉し、05側でスキップ制御を実装するだけでよい |
| 5. 都道府県単位のGeoJSON出力 | `geojson.writer.write_geojson`, `geojson.naming.build_geojson_filename`, `common.index_store.upsert_entry/save_index` | **Covered(条件付き)**: 書き込み経路自体は再利用可能。ただし要件8のマージのため「既存ファイルの読み戻し」が別途必要(下記参照) |
| 6. レジューム(中断・再開) | `scraping.resume.UrlResumeTracker`, `common.resume_store.ResumeStore` | **Covered**: キー設計(範囲ごとに分けるか等)のみ設計判断が必要 |
| 7. リクエスト頻度制御 | `scraping.fetcher.PageFetcher`(内部で`common.rate_limiter.RateLimiter`を使用) | **Covered**: 05は`PageFetcher`を使うだけで自動的に満たされる |
| 8. 廃止された道の駅の扱い | なし | **Missing(重大)**: (a) `FacilityProperties`への削除フラグ・最終確認日時フィールド追加(03拡張、要件定義で合意済み)。(b) **既存GeoJSONファイルをFacilityFeature列へ読み戻す機能が現状存在しない**(`geojson`パッケージは`to_feature_collection_dict`のみで逆方向の変換がない)。(c) 1年経過判定に使う時刻源の統一 |
| 9. 動作ログの記録 | `common.logging_setup.get_logger`/`log_scrape_started`/`log_scrape_finished`/`log_scrape_failed` | **Covered**: 既存ヘルパーで開始・終了・失敗は賄える。都道府県別件数・スキップ件数・削除状態遷移件数の集計ログは05側で`logger.info`を追加するだけで新規モジュールは不要 |

## Implementation Approach Options

### Option A: 05を新規パッケージのみで完結させる(03へは触れない)

- **内容**: 削除フラグ・最終確認日時を03のスキーマに追加せず、05独自のサイドファイル(例: `.resume/`と同様の`michinoeki-state.json`)で削除状態・最終確認日時を管理し、GeoJSON出力は「現在アクティブな施設のみ」を反映する
- **Trade-offs**:
  - ✅ 実装完了済みの03に手を入れない(revalidationの連鎖を避けられる)
  - ✅ 05単独で完結し、06への影響もない
  - ❌ **要件定義で確定した仕様(削除フラグをGeoJSONの施設プロパティとして持たせる)を満たせない**。消費側アプリが削除フラグを見るには別ファイルの参照が必要になり、要件8の意図(単一のGeoJSONで判別可能)から外れる
  - ❌ 要件定義フェーズで既にOption Bに相当する方針(03拡張を前提として進める)が明示的に決定済みのため、後戻りになる

### Option B: 03-geojson-schemaを拡張し、05は新規パッケージを追加する(要件定義で合意した方針)

- **どのファイルを拡張するか**:
  - `geojson/models.py`: `FacilityProperties`に削除状態を表す項目(例: `is_deleted: bool = False`, `last_confirmed_at: datetime | None = None`)を追加
  - `geojson/validation.py`: 新項目の型・整合性チェックを追加(必要に応じて)
  - `geojson/writer.py`または新規`geojson/reader.py`: **既存GeoJSONをFacilityFeature列へ読み戻す関数の追加**(現状皆無のため新規)
  - `geojson/models.py`の`_properties_to_dict`/JSONキー: 新項目のシリアライズ(省略条件含む)を追加
- **互換性評価**: 新規フィールドはすべて任意項目(デフォルト値あり)で追加するため、既存の`to_feature_collection_dict`の出力に対しては後方互換(6-sapa-scrapingは未実装なので破壊的影響なし)。ただし03は`phase: "implementation-complete"`のため、revalidation triggersに従い03側でのタスク追加・再検証が必要
- **05側の新規パッケージ**: `src/roadstop_scraper/michinoeki/`(仮)配下に、範囲指定・地方区分対応表・一覧収集・詳細抽出(座標正規表現・施設設備マッピング)・削除状態マージ・エントリポイントを実装
- **Trade-offs**:
  - ✅ 要件定義で合意した仕様(削除フラグをGeoJSON施設プロパティとして保持)をそのまま満たせる
  - ✅ 03/04と同じ「spec単位サブパッケージ+`__init__.py`公開API集約」パターンを踏襲でき、既存の設計スタイルと整合する
  - ❌ 実装完了済みの03を再度開くコスト(タスク・テストの追加、revalidation triggersの発火)
  - ❌ 「既存GeoJSON読み戻し」という、03の設計時に想定されていなかった新規責務が生じる(03のBoundary Commitmentsの見直しが必要になる可能性)

### Option C: Hybrid — 03へは最小限の型追加のみ行い、読み戻し・マージロジックは05に置く

- **内容**: 03には`FacilityProperties`へのフィールド追加と`to_feature_collection_dict`のシリアライズ対応のみを依頼し、「既存GeoJSONの読み戻し」自体は03のAPIを使わず05が`json.loads`で直接パースして最小限の情報(施設名称等のキー相当・削除フラグ・最終確認日時)だけを取り出す軽量な自前ロジックとする
- **Trade-offs**:
  - ✅ 03への変更を型定義追加のみに限定でき、03のBoundary(書き込みゲートウェイとしての責務)を壊さない
  - ✅ 03の再検証範囲が小さく済む
  - ❌ 05が`geojson`パッケージの内部スキーマ知識(JSONキー名等)に依存する形になり、03のスキーマ変更時に05側でも追随が必要になる密結合が生じる
  - ❌ 「読み戻し」がプロジェクト全体でも05にしか存在しないため、06-sapa-scrapingが将来同種の要件を持った場合に重複実装になりうる

## Effort & Risk

- **地方区分↔都道府県対応表**: Effort S / Risk Low — 47件の静的データ追加のみ。所有場所(03 or 05)の判断のみ設計で必要
- **一覧ページ収集ロジック**: Effort S–M / Risk Medium — `PageFetcher`/`HtmlPage`の組み合わせで実装できるが、詳細ページURL抽出セレクタは実地調査が必要
- **詳細ページ抽出(座標の正規表現抽出・18種施設設備マッピング)**: Effort M / Risk Medium — 既存の`extract.FieldSpec`では賄えない座標抽出・アイコン判定は新規ロジックが必要。実HTMLの正確な構造が未確認
- **03スキーマ拡張(フィールド追加)**: Effort S / Risk Medium — 変更自体は小さいが、実装完了済みspecの再オープンという運用上のコストがある
- **既存GeoJSON読み戻し機能の追加**: Effort M / Risk Medium–High — プロジェクトに前例のない新規責務。所有場所(03 or 05)次第で境界定義のやり直しが発生しうる
- **削除状態マージ・1年保持ロジック**: Effort M / Risk Medium — 新規のドメインロジックで既存パターンの流用が効きにくい(active/deleted/purgeの状態遷移をゼロから設計)
- **実行エントリポイント(範囲指定引数)**: Effort S–M / Risk Low–Medium — プロジェクト初のCLI/エントリポイントとなるため形式の確立が必要だが、技術的な難度は低い
- **レジューム・レート制限・ロギング統合**: Effort S / Risk Low — 既存コンポーネントの組み合わせのみ
- **総合**: Effort **L(1〜2週間)** / Risk **Medium**(既存基盤の再利用度は高いが、03再オープンと未経験の読み戻し・削除マージロジックが不確実性の中心)

## Recommendations for Design Phase

- **Preferred approach**: Option B(03拡張+05新規パッケージ)を軸としつつ、「既存GeoJSON読み戻し」の置き場所についてはOption CのようなミニマルAPI(03側に`parse_feature_collection_dict`相当の型変換関数だけを追加し、ファイルI/O自体は05が担う)によって03の責務を書き込みゲートウェイのまま保つ折衷を検討する
- **Key decisions carried to design**:
  - 03へ追加するフィールド名・型(`is_deleted`/`deleted_at`等の命名、`last_confirmed_at`の型と`index.json`の`updated_at`との時刻源統一)
  - 既存GeoJSON読み戻しAPIの所有モジュール(03の新規`reader.py` or 05内部の軽量パーサ)
  - 地方区分↔都道府県対応表の所有モジュール(03の`prefectures.py`拡張 or 05専有。06との将来共有を考慮)
  - `UrlResumeTracker`のキー設計(範囲(全国/地方/都道府県)ごとに分けるか、単一キー`"michinoeki"`に統一するか)
  - 実行インタフェースの形式(pyproject `scripts` エントリポイント、`argparse`ベースの`__main__.py`、または関数API + 呼び出し側スクリプト)
- **Research Needed (carried forward)**:
  1. michi-no-eki.jpの一覧/検索ページ(`/stations/search/{都道府県コード}/all/all`)の詳細ページリンクの正確なセレクタ・ページネーション有無
  2. 詳細ページの18種施設設備アイコンのDOM構造・class命名規則(`facility01`〜`18`・`_off`判定の実装方法)
  3. マップコード表示箇所の正確なセレクタ
  4. Google Maps embed URL(`google.com/maps/embed/v1/place?q={lat},{lon}`)を保持する要素・属性の正確なセレクタと、クエリパラメータからの座標抽出の正規表現設計
  5. 1年経過判定に用いる時刻源(`python_util.time_utility`のJST時刻 vs 標準`datetime.now(timezone.utc)`)と、既存`index.json`/GeoJSONのタイムスタンプ形式との整合方針

---

## Design Discovery Summary

- **Feature**: `05-michinoeki-scraping`
- **Discovery Scope**: Extension(light discovery)。ただしギャップ分析で洗い出した「Research Needed」5項目はいずれも対象サイトの実HTML確認が前提のため、`curl`による実地調査を実施した(2026-07-15、`michi-no-eki.jp`の詳細ページ2件・一覧/検索ページ2件を実測)
- **Key Findings**:
  - **座標は詳細ページのGoogle Maps埋め込みURLではなく、一覧/検索ページの地図マーカー用データ属性(`div.js-data-box`の`data-lat`/`data-lng`)から取得できる**。この属性は該当都道府県の全件が1ページ目に(ページネーションと無関係に)含まれるため、Google Maps APIキーへの依存も正規表現によるURL解析も不要になる
  - 一覧/検索ページの詳細カード自体は36件/ページでページネーションされるが、`js-data-box`の地図マーカー一覧は全件が常に同一ページに埋め込まれているため、**列挙・座標取得にページネーション処理は不要**
  - 施設設備18種は`.viewFacility li`要素のclass(`off`の有無)と`span`テキスト(日本語ラベルそのもの)で判定でき、`facility01`〜`18`という連番とラベルの対応表を05側で自作する必要はない(サイトが常にラベル文字列を埋め込んでいる)
  - 詳細ページの項目群(`.info dl`内の`dt`/`dd`)はラベル文字列(道の駅名・所在地・TEL・駐車場・営業時間・ホームページ・ホームページ2・マップコード)で一貫しており、`ホームページ2`はWebサイトが1件のみの施設でも常に(空の)dt/dd対として出力される。位置に依存せずラベル文字列をキーに辞書化する方式が最も頑健
  - 対象サイトの一覧/検索ページURL(`/stations/search/{サイト内都道府県コード}/all/all`)が使う都道府県コードは、`03-geojson-schema`の公式コード(全国地方公共団体コード準拠、01〜47)とは**異なる独自の番号体系**(例: 北海道=10、沖縄=56)である。47件の対応表(サイト内コード↔公式コード)が05に必要
  - `HtmlPage`(04所有)には繰り返し要素の**属性値**をリストで取得する手段(`find_texts`のテキスト版はあるが属性版がない)が存在せず、`data-name`/`data-link`/`data-lat`/`data-lng`のような複数属性の相関抽出ができない。04への後方互換な追加メソッドが必要
  - `geojson`パッケージ(03所有)には`to_feature_collection_dict`(書き込み方向)のみでGeoJSON読み戻し(逆方向)がなく、要件8の前回状態マージには追加が必要(ギャップ分析で既出)

## Research Log

### 詳細ページのDOM構造実測

- **Context**: 要件3(詳細情報抽出)の実装可能性と、`extract.FieldSpec`で賄えるかを確認するため
- **Sources Consulted**: `https://www.michi-no-eki.jp/stations/views/18786`(三笠)・`/18787`(スタープラザ芦別、北海道)・`/19813`(許田)・`/19814`(おおぎみ、沖縄)の実HTML(`curl`実測、2026-07-15)
- **Findings**:
  - `.info dl`が8件固定で並ぶ: `dt`=道の駅名/所在地/TEL/駐車場/営業時間/ホームページ/ホームページ2/マップコード、各`dd`にテキスト(TEL・ホームページは`<a>`内テキスト)
  - 所在地`dd`は`"068-2165 北海道三笠市岡山1056-1"`のように郵便番号+住所が半角スペース区切りで連結(正規表現`^(\d{3}-\d{4})\s*(.*)$`で分離可能)
  - 駐車場`dd`は`"大型：13台　普通車：202（身障者用2）台"`または`"大型：9台　普通車：109（うち身障者用3）台"`のように、身障者用の前置詞(「うち」の有無)に揺れがある。`大型：(\d+)台`・`普通車：(\d+)`・`身障者用(\d+)`をそれぞれ独立した`re.search`で抽出すれば揺れを吸収できる
  - `ホームページ2`はWebサイトが1件のみの施設(おおぎみ)でも`<dt>ホームページ2</dt><dd><a href="" target="_blank"></a></dd>`として出力される。空文字は「値なし」として扱う必要がある
  - 施設設備は`div.viewFacility ul li`(18件固定)。無効な項目は`<li class="off">`、有効な項目は`class`属性なし。いずれも`<span>ラベル</span>`に日本語ラベルがそのまま入っている(例: `ATM`, `EV充電施設`)
  - マップコードは他のdt/ddと同一パターンで取得可能(`180 276 269`形式、ハイフンなしスペース区切り)
- **Implications**: `.info dl dt`と`.info dl dd`をそれぞれ`find_texts`で取得し、zipしてラベル→値の辞書を構築する方式が、位置固定に頼らず頑健(要素数が変動しても対応するラベルで参照できる)。施設設備は`.viewFacility li:not(.off) span`のテキスト取得のみで済み、`facilityNN`という番号とラベルの対応表を05独自に持つ必要はない

### 一覧/検索ページの構造実測とページネーション調査

- **Context**: 要件2(一覧収集)の実装方式と、ページネーションの有無を確認するため
- **Sources Consulted**: `https://www.michi-no-eki.jp/stations/search/10/all/all`(北海道、`?page=0,1,2,3`の4ページ)・`/stations/search/56/all/all`(沖縄)の実HTML(`curl`実測、2026-07-15)
- **Findings**:
  - 一覧ページには2種類のマークアップが存在する: (1) 36件/ページでページネーションされる詳細カード(`<a href="/stations/views/{id}">`ほか)、(2) **ページネーションと無関係に、該当都道府県の全件が同一ページに埋め込まれる地図マーカー用`<div class="js-data-box" data-name="{名称}" data-link="/stations/views/{id}" data-lat="{緯度}" data-lng="{経度}">`**
  - 北海道(128件)・沖縄(10件)のいずれも、1ページ目の`js-data-box`件数が最終ページまでの累計件数と一致することを確認(`page=0`と`page=1`で`data-link`の集合が完全一致)
  - ページネーションのURLは`?page=N`(N=0始まり)で、`.pagination`要素から総ページ数を確認できるが、`js-data-box`を使えばページネーション自体を辿る必要がない
- **Implications**: 一覧収集(要件2)は`js-data-box`要素の`data-name`/`data-link`/`data-lat`/`data-lng`を1回のページ取得で全件抽出すれば十分。名称・座標・詳細URLをこの1ページから得られるため、要件3の緯度経度抽出もこの一覧ページのデータに一本化でき、詳細ページ側でのGoogle Maps埋め込みURL解析(正規表現でのクエリパラメータ抽出、Google APIキー露出への依存)は不要になる

### サイト内都道府県コードと公式都道府県コードの対応調査

- **Context**: 一覧/検索ページURL(`/stations/search/{コード}/all/all`)の構築に必要なコードが、`03-geojson-schema`の公式コード(全国地方公共団体コード準拠)と同一かを確認するため
- **Sources Consulted**: 詳細ページ下部の地方区分ナビゲーション(`北海道・東北エリア`等8ブロック、都道府県名と`/stations/search/{コード}/all/all`のリンクを保持)
- **Findings**:
  - サイト内コードは`10`=北海道、`11`=青森、…、`56`=沖縄という独自の連番で、`03`の公式コード(`01`=北海道、…、`47`=沖縄)とは一致しない
  - サイトのナビゲーションは8地方に区分されているが、その区分(「北海道・東北」を1つに統合、「北陸」を独立区分として持つ)は、要件1で運用者向けに定義した8地方区分(北海道・東北・関東・中部・近畿・四国・中国・九州沖縄を独立区分とし、北陸は中部に含む)とは異なる。サイトのナビゲーション区分はURL構築に使わない(あくまで参考情報)
- **Implications**: 05は「サイト内コード↔公式コード」の47件対応表(URL構築用)と、「要件1の8地方区分↔公式コード」の対応表(範囲指定用)を、独立した2つの参照データとして持つ必要がある。いずれも`03-geojson-schema`の`prefectures.py`(コード↔ローマ字/日本語名)とは別の関心事であり、05専有のデータとする

### `HtmlPage`の属性抽出APIの過不足確認

- **Context**: `js-data-box`から`data-name`/`data-link`/`data-lat`/`data-lng`という複数属性を要素ごとに相関させて取得する必要があり、既存`HtmlPage`(04所有)のAPIで賄えるかを確認するため
- **Sources Consulted**: `src/roadstop_scraper/scraping/parser.py`の実装
- **Findings**: `find_text`/`find_texts`/`find_attr`/`require_text`/`require_attr`のみが存在し、「セレクタに一致する全要素の、ある属性の値」をリストで返す手段(`find_texts`の属性版)がない。`find_attr`は最初の一致要素のみを返すため、128件全件の相関抽出には使えない
- **Implications**: `HtmlPage`に`find_attrs(selector: str, attribute: str) -> list[str | None]`(`find_texts`と対の、属性版)を追加する後方互換な拡張が必要。05は同一セレクタに対して`data-name`/`data-link`/`data-lat`/`data-lng`それぞれで`find_attrs`を呼び、DOM順序が一致する前提でインデックスを揃えて`zip`する

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| A: 05完結(03非変更) | 削除状態を05独自のサイドファイルで管理 | 03に触れない | 要件8(GeoJSON施設プロパティとして削除フラグを持つ)を満たせない | 要件定義で既に却下済み |
| B: 03フル拡張(read/write両方を03に実装) | 03に`FacilityStatus`・`last_confirmed_at`と読み戻し関数を追加 | 03が書き込み・読み込み双方の正になり一貫する | 03の責務(検証ゲート付き書き込みゲートウェイ)が読み込みにも広がる | 採用(下記Design Decisions参照) |
| C: 03最小拡張+05が生JSON解析 | 03はフィールド追加のみ、読み戻しは05が`json.loads`で自前実装 | 03への変更が最小 | 05が`geojson`の内部JSONキー名に密結合し、06実装時に重複しうる | 不採用(密結合と重複のリスクがOption Bの追加コストを上回らない) |

## Design Decisions

### Decision: 座標の取得元を一覧ページの`js-data-box`に一本化する

- **Context**: 要件3.1(緯度経度の抽出)をどのページ・どの手段で満たすか
- **Alternatives Considered**:
  1. 詳細ページのGoogle Maps embed URL(`google.com/maps/embed/v1/place?q={lat},{lng}&key=...`)を`find_attr`+正規表現で解析
  2. 一覧/検索ページの`div.js-data-box`が持つ`data-lat`/`data-lng`属性をそのまま利用
- **Selected Approach**: 2(一覧ページの`data-lat`/`data-lng`)
- **Rationale**: 詳細ページ側は露出したGoogle APIキーへの依存と正規表現解析の追加実装が必要になるのに対し、一覧ページ側は既に構造化された属性値であり、かつ一覧収集(要件2)と同一リクエストで名称・詳細URL・座標を同時に取得できるため、詳細ページへのリクエスト回数(要件7のレート制限対象)も増えない
- **Trade-offs**: 一覧ページのマークアップ変更(`js-data-box`の廃止等)に対する構造変化検知が、詳細ページとは別に必要になる。ただし`HtmlPage.require_attr`相当の必須取得APIを一覧ページのパースにも適用することで、既存の`StructureChangedError`の枠組みをそのまま使える
- **Follow-up**: 実装時に、複数都道府県で座標欠落(`data-lat`/`data-lng`が空)のケースがないか追加サンプルで確認する

### Decision: `04-scraping-engine`に`HtmlPage.find_attrs`を追加する

- **Context**: `js-data-box`の複数属性を要素ごとに相関させて取得する手段が`HtmlPage`にない
- **Alternatives Considered**:
  1. 05が`bs4`を直接importして自前でパースする
  2. `HtmlPage`に`find_attrs(selector, attribute) -> list[str | None]`を追加する
- **Selected Approach**: 2
- **Rationale**: 04の設計は「bs4のimportは`scraping/parser.py`内に閉じる」「05/06がbs4を直接importすることは禁止」と明記しており、1は04のBoundary Commitmentsに反する。2は`find_texts`と対称的な最小限の追加で、既存メソッドのシグネチャ変更を伴わない後方互換な拡張
- **Trade-offs**: 04(実装完了済み)への再オープンが必要。ただし追加のみで既存契約は変更しないため、04のRevalidation Triggers(シグネチャ変更)には該当しない
- **Follow-up**: 05の実装は、`data-name`/`data-link`/`data-lat`/`data-lng`それぞれに対する`find_attrs`呼び出しの戻り値配列が同じ長さ・同じDOM順序であることを前提にする。この前提が崩れる(要素によって属性が欠落する等)場合の扱いは実装時にテストで担保する

### Decision: 03-geojson-schemaに削除状態フィールドと読み戻し関数を追加する

- **Context**: 要件8(廃止駅の削除フラグ・1年保持)の実現方式
- **Alternatives Considered**: ギャップ分析のOption A/B/C(上記Architecture Pattern Evaluation参照)
- **Selected Approach**: Option B — `FacilityProperties`に`status: FacilityStatus`(`StrEnum`、値は`"active"`/`"deleted"`、既定`ACTIVE`)と`last_confirmed_at: datetime | None`を追加し、`geojson`パッケージに読み戻し関数(`from_feature_collection_dict`と`geojson/reader.py`の`read_geojson`)を新設する
- **Rationale**: 削除フラグをGeoJSONの施設プロパティとして持たせるという要件定義時の合意を素直に満たし、かつ「読み戻し」を`geojson`パッケージ内に置くことで、JSONキー名等の内部スキーマ知識への05の密結合を避けられる(Option Cの密結合リスクを回避)
- **Trade-offs**: 03の書き込みゲートウェイという性質(Boundary Commitments)に読み込み責務が加わるため、03の設計書自体の改訂(Boundary Commitments・Components and Interfacesへの追記)が必要になる
- **Follow-up**: `status`が`ACTIVE`の場合はJSON出力で省略(既存データとの後方互換・簡潔さを優先)し、`"status": "deleted"`のときのみキーを出力する。`last_confirmed_at`はISO 8601文字列(`index_store`と同じ`isoformat()`)で、値がある限り常に出力する

### Decision: 時刻源を`python_util.time_utility`のJST時刻に統一する

- **Context**: `last_confirmed_at`の記録・1年経過判定・`index.json`の`updated_at`更新で使う時刻源
- **Alternatives Considered**: 標準`datetime.now(timezone.utc)` / `python_util.time_utility`(JST)
- **Selected Approach**: `python_util.time_utility`
- **Rationale**: `02-common-infra`の設計が`index.json`の`updated_at`生成に`python_util.time_utility`のJST時刻を使う方針を既に確立しており、同一実行内で複数の時刻源が混在すると1年経過判定と`index.json`更新のタイムスタンプがずれるリスクがある
- **Trade-offs**: なし(既存方針への追随)

### Decision: サイト内都道府県コード・地方区分の対応表は05専有とする

- **Context**: 「サイト内コード↔公式コード」「8地方区分↔公式コード」という2つの参照データを、`03-geojson-schema.prefectures`へ拡張するか05専有とするか
- **Alternatives Considered**: 03の`prefectures.py`へ両対応表を追加 / 05専有の新規モジュールとする
- **Selected Approach**: 05専有(`michinoeki/site_urls.py`・`michinoeki/scope.py`)
- **Rationale**: サイト内コードは対象サイト(michi-no-eki.jp)固有の実装詳細であり、03の「都道府県コード↔ローマ字/日本語名」という共通スキーマの関心事とは異質。8地方区分は06-sapa-scrapingでも将来必要になりうるが、対象サイトが異なれば地方区分自体の要否・粒度も独立に決まりうるため、現時点で03へ先取りして共通化せず、05専有としたうえで06実装時に重複が判明した場合に共通化を検討する(YAGNI)
- **Trade-offs**: 06実装時に同種のテーブルが再実装される可能性がある。ただし47件の静的データであり複製コストは小さい

## Risks & Mitigations

- 一覧ページの`js-data-box`マークアップが将来変更される(地図機能の実装変更等) — 必須属性取得に`require_attr`相当の構造変化検知を適用し、`StructureChangedError`で早期に検知する
- 駐車場`dd`のテキスト表記に未知のバリエーションがある(調査した4件以外の表記揺れ) — 「大型／普通車／身障者用」いずれも独立した`re.search`とし、一致しない場合は該当項目のみ`None`とする(全体を失敗させない)
- 03・04への追加型拡張(後方互換)が、実装完了済みspecの再オープンという運用コストを伴う — 追加は新規フィールド・新規メソッドのみで既存契約を変更しないため、03・04のRevalidation Triggers(シグネチャ変更等)には該当しないことを設計上明記する

## References

- [道の駅公式ホームページ 全国「道の駅」連絡会](https://www.michi-no-eki.jp/) — 対象サイト本体
- `https://www.michi-no-eki.jp/stations/views/18786` ほか3件 — 詳細ページのDOM構造実測(2026-07-15)
- `https://www.michi-no-eki.jp/stations/search/10/all/all` ほか — 一覧/検索ページのDOM構造・ページネーション実測(2026-07-15)
