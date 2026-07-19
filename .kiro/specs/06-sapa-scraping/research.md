# Research & Design Decisions: 06-sapa-scraping

## Summary
- **Feature**: `06-sapa-scraping`
- **Discovery Scope**: Complex Integration(既存パイプラインの拡張+未選定の外部サイト複数+ジオコーディング新規統合)
- **Key Findings**:
  - 全国のSA/PAを単一サイトでは収集できない。NEXCO東日本(driveplaza.com)・中日本(sapa.c-nexco.co.jp)・西日本(w-holdings.co.jp)の3公式サイトを情報源とするマルチサイト構成が必須
  - 3サイトとも一覧・詳細HTMLに緯度経度を直接掲載していない(地図はJS動的描画)。詳細ページには郵便番号付き住所があるため、住所→座標のジオコーディング(国土地理院 AddressSearch API)が座標取得の実質的な主経路になる
  - 上下線は東日本では別URL(`/sapa/{道路}/{施設}/{1|2}/`)、中日本では施設名の「(上り)/(下り)」表記で区別され、詳細ページURL(`source_url`)は上下線別Featureのマージキーとして機能する
  - 一覧はどのサイトも道路・エリア単位で、都道府県単位の一覧は存在しない。都道府県の特定は詳細ページの住所からの導出が必要

## Research Log

### 情報源の選定(全国のSA/PAをカバーするサイト構成)
- **Context**: Gap分析のResearch Needed 1。対象サイトが未選定で、単一サイトで全国をカバーできるかが不明だった
- **Sources Consulted**: [ドラぷら SA/PA検索](https://www.driveplaza.com/dp/SAPAService)、[検索結果例](https://www.driveplaza.com/dp/SAPAServRes?HIGHWAY=AA)、[NEXCO中日本 サービスエリア](https://sapa.c-nexco.co.jp/search/result)、[NEXCO西日本 SA・PA情報サイト](https://www.w-holdings.co.jp/map_search/)
- **Findings**:
  - ドラぷらの道路名一覧は全国を列挙するが、SA/PA検索の対象は「NEXCO東日本管内のみ」と明記。エリア軸(北海道〜九州・沖縄)+道路軸の検索構造
  - NEXCO中日本は`sapa.c-nexco.co.jp/search/result`で216件(全域)、ページネーションあり。詳細URLは`/sapa?sapainfoid={id}`。絞り込み軸はエリア(関東・静岡/甲信/東海・滋賀/北陸)と路線
  - NEXCO西日本は`w-holdings.co.jp`が公式SA・PA情報サイト。約30路線の道路別絞り込み。地図検索はJS動的描画で静的HTMLから座標は取得不可
  - 一覧HTMLに住所・座標・都道府県は含まれない(3サイト共通)。東日本の一覧には駐車場台数(大型/小型)が載る
- **Implications**: サイトごとの差異(一覧単位・URL形式・表記)を吸収するサイトアダプタ抽象が必要。都道府県単位の実行範囲(R1)と一覧単位(道路・エリア)のミスマッチを、詳細ページの住所からの都道府県導出+出力前フィルタで埋める設計になる

### 実装タスク3.1-3.3での追加実測(2026-07-19)
- **Context**: 各サイトアダプタの実装着手時に、実ページへの追加アクセスでセレクタ・URLパターンを確定した(タスク3.1-3.3の観測可能な完了条件)
- **Findings**:
  - **東日本**: 検索フォーム(`/dp/SAPAService`)の`arealist`パラメータ(0=全国〜10=九州・沖縄)を実測。一覧(`div.box-sapa`)・詳細に2種類のテンプレート(標準/`Pasar`ブランド)が存在することを確認し、両対応で実装した。**[2026-07-20追記による訂正]** この時点の実測は`arealist=1`のレスポンスを「北海道エリアの検索結果ページ」と誤認していたが、タスク6.3での追加のライブ検証により、これは誤りだったことが判明した(`arealist`は`HIGHWAY=AA`併用時に値によらず東日本管内全域を返すため、`arealist=1`のレスポンスは北海道限定ではなく東日本管内全域~875件だった)。詳細は下記「タスク6.3での実サイト疎通確認」のログを参照
  - **中日本**: 検索結果(`/search/result`)はモバイル(`#page_sp`)・PC(`#page`)の重複表示があり、`#page`のみを使用する必要がある。**ページネーション(`paging()`のJS駆動)は`/search/Page`・`?PageNum=`のいずれの静的リクエストでも再現できず、1ページ目(216件中20件)のみ取得可能という制約が確定した**(タスク6.3での実サイト調査対象として持ち越し)。詳細ページの`a[href*="google.com/maps"]`リンクから`@{lat},{lon},{zoom}`形式で**直接座標を取得できることを発見**(「3サイトとも座標非掲載」という当初の前提を部分的に修正)
  - **西日本**: `/service_search/`・`/purpose_search/`にサーバレンダリングの一覧HTMLが存在しないことを確認(実測で0件)。実際の一覧データは`/js/map_search.js`が参照する`https://www.w-holdings.co.jp/sapa/json/map-search.json`(310件・緯度経度を含むJSON)から取得される構造であることが判明。`HtmlPage`/`parse_html`はJSONテキストから構造化データを復元できないことを実測で確認(`find_text("body")`が`None`を返す)
- **Implications**:
  - 中日本のページネーション未解決は、全国のSA/PAデータセットの完全性に対する既知のギャップ(中日本管轄の216件中20件のみ収集)。タスク6.3(実サイト疎通確認)での優先調査項目とする
  - 西日本のJSON専用一覧という発見は、`SapaSite`プロトコル(`parse_listing(page: HtmlPage) -> SapaListingResult`)が全サイトHTML前提だったことと矛盾したため、プロトコルへ`listing_kind: Literal["html", "json"]`属性を追加し、`parse_listing`の引数型を`HtmlPage | object`へ拡張した(東日本・中日本は`listing_kind = "html"`の1行追加のみで無変更)
  - 西日本のJSON側にのみ存在する直接座標(`latitude`/`longitude`)は、現行の`SapaStub`/`SapaListingResult`型に運搬用フィールドが無いため活用されず、西日本の全施設は常にジオコーディング(4.2)へフォールバックする。将来的に`SapaStub`へ座標フィールドを追加する設計見直しの候補として残す

### タスク6.3での実サイト疎通確認: 東日本arealistパラメータの未機能を発見(2026-07-20)
- **Context**: タスク6.3(実サイト疎通確認)で`sapa-scrape --prefecture-code 01`(北海道のみ)を実行したところ300秒超で終了せず、東北道(埼玉)・常磐道(茨城)・秋田道(秋田)等、北海道以外の道路コードの施設を処理し続けていることが判明し、`east.py`の`arealist`によるエリア絞り込みの前提を疑い、実サイトへの直接検証を行った
- **Sources Consulted**: curlによるライブ検証(`https://www.driveplaza.com/dp/SAPAServRes`への直接GETリクエスト)
- **Findings**:
  - `curl 'https://www.driveplaza.com/dp/SAPAServRes?arealist=1&HIGHWAY=AA'` → `div.box-sapa`875件、道路コードは1010・1020・1030・…・9031など東日本管内全域にわたる(北海道限定ではない)
  - `curl 'https://www.driveplaza.com/dp/SAPAServRes?arealist=0&HIGHWAY=AA'` → 同じく875件、`arealist=1`の結果と完全に同一(バイト単位で一致)
  - `curl 'https://www.driveplaza.com/dp/SAPAServRes?arealist=1'`(`HIGHWAY`省略)→ 0件(`HIGHWAY`パラメータ自体は必須だが、値`AA`が何を意味しても結果は変わらない)
  - **結論**: `arealist`は`HIGHWAY=AA`併用時、値によらず常に東日本管内全域(~875件)を返す。サーバ側のエリア絞り込みは実質的に機能していない。実サイトの本来のエリア絞り込みは(もし存在するなら)JS駆動のフォーム送信等、静的GETリクエストでは再現できない別の仕組みによるものと推測されるが、これ以上の解明はスコープ外とする
- **Implications**:
  - 「正しさ」への影響は無い: `sapa/collector.py`の`collect_site`は各施設の住所から都道府県を導出し、範囲外の施設を出力に含めない既存ロジックを持つため、最終的なGeoJSON出力は要求都道府県のみを正しく含む
  - 「効率」への影響は重大: 東日本管内のいずれか1都道府県でも要求されると、修正前の実装は`arealist`値ごとに複数の重複URLを構成し、同一の875件全域一覧を何度も(あるいは1度でも)取得し、その875件全ての詳細ページ取得(および必要に応じてジオコーディング)を行っていた。これは「サードサーバへの負荷を抑える」という原則への重大な違反であり、狭い範囲の実行が数十分単位の実行時間になる原因だった
  - **適用した修正**: `east.py`の`listing_urls`を、要求都道府県が東日本管内(北海道〜北陸)と交差する場合は常に単一の全域URL(`arealist=0`)のみを返すよう変更した(複数の重複URLの構成をやめた)。都道府県への絞り込みは一覧取得の時点では行わず、既存のcollector側の住所ベース絞り込みに完全に委ねる。東日本管内を対象とする実行が常に管内全域(~875件)の詳細取得を伴うこと自体は実サイト側にサーバ側フィルタが存在しないという制約に起因し、本アダプタでは解消できない既知の制限として文書化した(design.md「sapa.sites」節のImplementation Notes参照)

### 詳細ページの提供フィールド(東日本で実測)
- **Context**: R3の抽出項目が対象サイトで取得可能かの確認
- **Sources Consulted**: [Pasar蓮田(上り)](https://www.driveplaza.com/sapa/1040/1040021/1/)
- **Findings**:
  - タイトルに「施設名(上り線)・道路名」形式で名称・上下線・路線名が揃う。方面はICマップ表記(「青森方面」等)
  - 住所は「〒349-0112 埼玉県蓮田市…」形式で郵便番号付き。**緯度経度はHTML内に存在しない**
  - 駐車場は「大型：132/小型：354」形式(05の「普通車」と区分名が異なる)。営業時間は施設単位の記述。電話番号は記載なし。施設設備(ガソリン・レストラン・コンビニ等)はアイコン列挙
- **Implications**: R3.1の必須項目(名称・路線名・緯度経度)のうち緯度経度はサイトから直接取れず、R4.2の補完(ジオコーディング)が例外系ではなく主経路になる。駐車場の「小型」は`Parking.standard`へマッピング。中日本・西日本の詳細構造は未実測(実装時の実測タスクで確定)

### ジオコーディング手段の選定
- **Context**: Gap分析のResearch Needed 3。04スペックから先送りされた「座標を取得できない情報源への代替手段」
- **Sources Consulted**: [国土地理院APIでジオコーディング](https://memo.appri.me/programming/gsi-geocoding-api)、[gsimaps Issue #29](https://github.com/gsi-cyberjapan/gsimaps/issues/29)、[ジオコーディングAPI比較](https://zenn.dev/rescuenow/articles/7386e8b17a16c5)
- **Findings**:
  - 国土地理院 AddressSearch API(`https://msearch.gsi.go.jp/address-search/AddressSearch?q={住所}`)は認証不要・無料。GeoJSON Feature配列(`geometry.coordinates`=[経度,緯度])を返す
  - 明示的なレート制限は公表されていないが、「地理院地図からの利用を主に想定」「恒久提供は保証されない」「サーバに過度の負荷を与えない」との条件付き。出典表示(国土地理院)が必要
  - 代替候補: Geolonia Community Geocoder(コミュニティ運営)、jageocoder(オフライン辞書型・辞書ファイルの導入が必要)、Yahoo!ジオコーダ(APIキー必要)
- **Implications**: 追加ライブラリなしで既存`PageFetcher.fetch_json`+`RateLimiter`をそのまま使えるGSI APIを採用。既存のリクエスト頻度制御(R8)をジオコーディングにも適用し、施設約900件(全国・上下線込み概算)なら1秒間隔でも実行時間は許容範囲。提供停止リスクは`GsiGeocoder`をモジュール分離して差し替え可能にすることで緩和

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 単一サイトスクレイパ(05の完全ミラー) | 1サイト前提で`michinoeki/`と対称の構成 | 最小の学習コスト | 全国をカバーできる単一サイトが存在しないため不成立 | 却下 |
| サイトアダプタ+共通収集ループ | `SapaSite`プロトコルで3サイトの差異を吸収し、収集・座標解決・マージは共通ループ | サイト追加(本四高速等)が局所変更で済む。テスト境界が明確 | プロトコル設計を誤ると個別サイトの特殊性が漏れ出す | **採用** |
| サイト別に独立した3スクレイパ | east/central/westを完全に別パイプラインとして実装 | サイト間の干渉ゼロ | 収集・補完・マージ・出力の4重複。削除判定の整合が困難 | 却下 |

## Design Decisions

### Decision: 情報源はNEXCO 3社の公式SA/PAサイトとする
- **Context**: 「全国の高速道路SA・PA」を収集できる単一の情報源が存在しない
- **Alternatives Considered**:
  1. ドラぷら単独 — NEXCO東日本管内のみで全国要件を満たせない
  2. 非公式集約サイト(NAVITIME等) — 利用規約リスクと構造安定性が公式サイトに劣る
- **Selected Approach**: NEXCO東日本(driveplaza.com)・中日本(sapa.c-nexco.co.jp)・西日本(w-holdings.co.jp)の3サイトを`SapaSite`アダプタとして実装し、管轄排他を前提に結果を統合する
- **Rationale**: 公式一次情報源であり、3社でNEXCO管轄の全SA/PAをカバーする
- **Trade-offs**: JB本四高速・都市高速等のNEXCO外の休憩施設は初期スコープ外(design.mdのNon-Goalsに明記)。3サイト分の実測・保守コスト
- **Follow-up**: 実装時の実測で(1)中日本・西日本の詳細ページ構造、(2)管轄境界の施設が複数サイトに重複掲載されないこと、を確認する

### Decision: 座標はジオコーディング(GSI AddressSearch)を主経路とする
- **Context**: 3サイトとも緯度経度をHTMLに掲載していない(R4)
- **Alternatives Considered**:
  1. 地図画面のJS内部データの解析 — 内部APIは非公開仕様で構造変化リスクが高く、負荷配慮の観点でも不適
  2. jageocoder(オフライン) — 外部リクエスト不要だが辞書ファイル管理の運用が増える
- **Selected Approach**: 詳細ページの住所を`GsiGeocoder`(GSI AddressSearch API、`PageFetcher.fetch_json`利用)で座標化する。サイトが座標を直接提供する場合(将来の構造変化・追加サイト)はそちらを優先する(4.1)
- **Rationale**: 追加依存ゼロ・認証不要で、既存のレート制限・リトライ基盤に乗る
- **Trade-offs**: ジオコーディング精度は町字レベルに落ちる場合がある(SA/PA敷地は広大なため地図ピン用途では許容)。API恒久提供の保証なし
- **Follow-up**: 出典表示(国土地理院)をREADMEへ記載。座標が日本の範囲外になった場合の棄却は既存`validation`の範囲検証に委ねる

### Decision: 都道府県の特定は詳細ページ住所の都道府県名前方一致で導出する
- **Context**: 一覧が道路・エリア単位のため、都道府県単位の出力(R6)・範囲指定(R1)・削除判定の限定(R9.5)に必要な都道府県が一覧からは決まらない
- **Selected Approach**: `sapa/address.py`が住所文字列から`PREFECTURES`の日本語名前方一致で`Prefecture`を導出する。導出できない施設は抽出失敗(3.6)。範囲指定時は、一覧・詳細の収集は関連エリア全体で行い、都道府県確定後にスコープ外の施設を出力対象から除外する
- **Rationale**: 住所は唯一全サイト共通で取得できる都道府県情報源。47都道府県名の前方一致は曖昧性がない(「京都府」と「東京都」は先頭一致で衝突しない)
- **Trade-offs**: 都道府県指定実行でも関連エリアの詳細取得が発生する(過剰取得)。ただしスコープ外と確定した施設はジオコーディングを行わず、コストを抑える
- **Follow-up**: 「山口県…広島県境」のような特殊表記の実在有無を実測で確認

### Decision: サイト単位の一覧取得失敗は「当該サイトの前回データ現状維持」で隔離する
- **Context**: R2.3(失敗範囲の中断と他範囲の継続)とR9(削除判定)の両立。1サイトの一覧欠落を全体の`listed_urls`欠落として扱うと、そのサイト管轄の全施設が一斉に削除状態へ遷移する(05の`ListingUnavailableError`と同型の事故)
- **Selected Approach**: 一覧取得はサイト単位で全ページ成功を要求し、失敗したサイトは当該実行から除外する。マージ時、前回GeoJSONの各施設を`source_url`のホスト名で管轄サイトへ帰属させ、失敗サイトに属する施設は削除判定対象から外してそのまま維持する。成功したサイト分の処理・出力は継続する
- **Rationale**: `source_url`のホスト名はサイト帰属を一意に決められる唯一の既存データであり、スキーマ拡張なしで実現できる
- **Trade-offs**: 失敗サイトの施設は`last_confirmed_at`が更新されないが、削除方向へ倒れないため安全側
- **Follow-up**: サイト全失敗時(3サイトとも失敗)はGeoJSON出力自体を行わないことをテストで保証

### Decision: `scope`・`merge`を共有層`pipeline/`へ移設し、05はimport置換で追従する(Gap分析Option C)
- **Context**: 実行範囲解決(REGIONS)と削除状態遷移が05と完全同一仕様で、複製は二重管理リスク(05 research.mdで予告済み)
- **Alternatives Considered**:
  1. `geojson/`へ移設 — 03スペックの所有範囲(スキーマ・検証・IO)に実行時関心が混入する
  2. `michinoeki/`から直接import — 兄弟パッケージ依存で「site固有→共通層」の一方向規約を破る
- **Selected Approach**: 新設`roadstop_scraper/pipeline/`(依存方向: site固有パッケージ → pipeline → geojson → 標準庫/common)へ`scope.py`・`merge.py`を無変更移設(mergeのdocstringの道の駅前提記述のみ一般化)。`michinoeki/`のimportと該当テストの配置を更新する。再exportシムは置かない(プロジェクト内部のみの利用のため)
- **Rationale**: 仕様の単一管理と依存方向規約の維持を両立する最小の移設
- **Trade-offs**: 05実装への変更が発生し、05スペックの再検証トリガに該当する(移設は無変更のため既存テストの移設+import修正で再検証可能)
- **Follow-up**: 移設後に05のテストスイート全体が通ることをタスクで保証

### Decision: 部分結果キャッシュは共通化せずsapa専用実装とする
- **Context**: Gap分析ではOption Cの共通化候補に`_PartialResultStore`を含めていた
- **Selected Approach**: sapaは収集単位が「サイト横断→都道府県へ後段グルーピング」で、05の「都道府県単位」と永続化構造が異なる(スキップ件数を都道府県別+都道府県不明バケットで保持する必要がある)ため、`sapa/collector.py`内に専用実装を持つ
- **Rationale**: 構造が異なるものを無理に一般化するより、小さな専用実装の方が保守しやすい(synthesis: Simplification)
- **Trade-offs**: 冪等追記・クリアタイミングの設計パターンは05から複製する(パターン重複は許容)

### Decision: 補完由来の記録はログのみとし、スキーマ拡張しない
- **Context**: R4.4「補完により座標を得たことを運用者が確認できる形で記録」。GeoJSONプロパティへの由来フラグ追加は03のスキーマ拡張になる
- **Selected Approach**: 施設単位のINFOログ(URL・住所・座標)+都道府県単位の補完件数集計ログ(R10.1)で満たす。スキーマは変更しない
- **Rationale**: requirements.mdのAdjacent expectationsが「03の追加拡張は前提としない」と明記しており、ログで運用者の確認要件は満たせる
- **Trade-offs**: 消費側アプリからは補完由来かどうか判別できない(現時点の要件に消費側での判別は含まれない)

### 上下線・名称正規化の方針(synthesis: Generalization)
- 上下線の正規化(サイト固有表記→`Direction`)と名称からの方向表記除去(「Pasar蓮田(上り)」→名称「Pasar蓮田」+`direction=上り`)は全サイト共通の関心事のため、`sapa/sites/`の共通ヘルパに置き、各アダプタから利用する
- 上下集約施設(方向の区別なし)は`direction=None`の単一Featureとして表現する(3.2のWhere条件が成立しないケース)

## Risks & Mitigations
- 中日本・西日本の詳細ページ構造が未実測 — 実装タスクの先頭で実測し、`SapaSite`アダプタのセレクタを確定する(05のタスク7.5実疎通と同じパターン)
- GSI AddressSearch APIの恒久提供保証なし — `GsiGeocoder`をモジュール分離し差し替え可能に。失敗時は当該施設スキップ(4.3)で実行全体は継続
- 管轄境界施設の複数サイト重複掲載 — 実測で確認。重複が判明した場合はサイト優先順位による重複排除を追加
- ジオコーディング精度(町字レベル) — 地図ピン用途では許容。出力前の座標範囲検証(既存validation)で異常値は検出
- 3サイト分の構造変化リスク — 04エンジンの`StructureChangedError`とサイト単位隔離により、1サイトの変化が他サイトへ波及しない

## References
- [ドラぷら サービスエリア検索](https://www.driveplaza.com/dp/SAPAService) — NEXCO東日本の一覧構造
- [NEXCO中日本 サービスエリア検索結果](https://sapa.c-nexco.co.jp/search/result) — 中日本の一覧構造(216件・ページネーション)
- [NEXCO西日本 SA・PA情報サイト](https://www.w-holdings.co.jp/) — 西日本の情報源
- [国土地理院 AddressSearch API解説](https://memo.appri.me/programming/gsi-geocoding-api) — ジオコーディング仕様
- [gsimaps Issue #29](https://github.com/gsi-cyberjapan/gsimaps/issues/29) — GSI API外部利用の位置づけ

---

# Gap Analysis: 06-sapa-scraping

分析日: 2026-07-18 / 対象: requirements.md(requirements-generated時点) / 手法: `.claude/skills/kiro-validate-gap/rules/gap-analysis.md` フレームワーク

## 1. 現状調査(Current State)

### 既存アセットの全体像

05-michinoeki-scrapingまでの実装により、SA/PAスクレイピングに必要な基盤の大部分が稼働済み:

| モジュール | 提供機能 | 06からの再利用性 |
|---|---|---|
| `scraping/`(04) | `PageFetcher`(`fetch_text`/`fetch_json`・リトライ・レート制限適用)、`parse_html`/`HtmlPage`(CSSセレクタ抽出・`find_attrs`/`require_text`)、`UrlResumeTracker`、`load_scraping_config`、例外体系(`ScrapingEngineError`系) | そのまま利用可(設計上06を利用側として想定済み) |
| `geojson/`(03) | `FacilityKind.SAPA`・`Direction`(上り/下り)・`road_name`/`area_direction`等のSA/PA固有フィールド定義済み。`build_geojson_filename`・`write_geojson`(出力前検証込み)・`read_geojson`・`PREFECTURES`/`find_prefecture` | そのまま利用可。`validation.py`は`direction`列挙値検証も実装済み |
| `common/`(02) | `RateLimiter`・`ResumeStore`・`index_store`(load/upsert/save)・`logging_setup`(`log_scrape_started`/`log_scrape_finished`) | そのまま利用可 |
| `michinoeki/`(05) | `scope.py`(REGIONS 8地方区分・`resolve_scope`)、`merge.py`(`merge_with_previous`: 削除状態遷移)、`runner.py`(`_PartialResultStore`・`run_prefecture`・`run_scope`)、`cli.py`、`listing.py`/`detail.py`/`site_urls.py` | パターンとして全面的に参照可。ただし一部は**michinoekiパッケージ専有**であり、06からの直接importは依存方向が不自然(後述) |

### 支配的なパターン・規約

- パッケージ構成: `site_urls`(URL構成)→`listing`(一覧)→`detail`(詳細抽出)→`merge`(削除状態遷移)→`runner`(オーケストレーション)→`cli`(エントリポイント)の層構成。依存方向は site固有パッケージ → `scraping`/`geojson`/`common` の一方向
- エントリポイント: `pyproject.toml` の `[project.scripts]`(`michinoeki-scrape`)。06は `sapa-scrape` 追加が自然
- テスト: `tests/{パッケージ名}/` に配置、日本語命名規則(`test_(目的)_(対象)が_(状態)だった場合_(結果)`)
- レジューム2層構造: `UrlResumeTracker`(URL単位の処理済みフラグ)+`_PartialResultStore`(都道府県単位の部分結果キャッシュ)。永続化順序(結果保存→`mark_processed`)による冪等性担保が確立済み
- 削除状態管理: `source_url`をマージキーとし、`listed_urls`(一覧で確認できた全URL)で「今回抽出できなかっただけ」と「一覧から消失」を区別する方式

### 05 research.mdで06へ先送りされた論点(今回顕在化)

- REGIONS・`resolve_scope`の所有場所: 「06実装時に重複が判明した場合に共通化を検討(YAGNI)」→ 要件1で同一の3単位指定が確定し、**重複が顕在化**
- 前回GeoJSONの「読み戻し」(`read_geojson`)+マージ: 「06が同種の要件を持った場合に重複実装になりうる」→ 要件9で同一の削除状態管理が確定し、**重複が顕在化**

## 2. 要件実現可能性分析(Requirement-to-Asset Map)

| 要件 | 既存アセット | ギャップタグ |
|---|---|---|
| R1 実行対象範囲の指定 | `michinoeki/scope.py`が完全に同一のロジックを保有 | **Constraint**: michinoeki専有のため所有場所の判断が必要(共通化 or 複製) |
| R2 SA/PA一覧の収集 | `PageFetcher`+`parse_html`(手段)、`listing.py`(パターン) | **Missing**(サイト固有実装)+**Unknown**: 対象サイトの一覧構造(都道府県単位か路線単位か・上下線の表現・ページネーション有無) |
| R3 詳細情報の抽出 | `detail.py`(ラベル辞書化パターン)、スキーマ側は`road_name`/`direction`/`area_direction`定義済み | **Missing**(サイト固有実装)+**Unknown**: 提供フィールド・上り/下り表記の正規化ルール・所在都道府県の特定方法 |
| R4 座標の取得と補完 | **該当実装なし**(コードベース全体にジオコーディング関連なし) | **Missing**(新規能力)+**Unknown**: 対象サイトの座標提供状況・補完手段の選定(外部API・データセット)。補完元サービスへの頻度制御も要検討 |
| R5 抽出失敗時のエラーハンドリング | `runner._collect_stubs`のスキップ+警告ログ+件数集計パターン | パターン再利用で対応可 |
| R6 都道府県単位のGeoJSON出力 | `build_geojson_filename(prefecture, FacilityKind.SAPA)`・`write_geojson`・`index_store` | **ギャップなし**(完全に流用可) |
| R7 レジューム | `UrlResumeTracker`(汎用・キー指定式)、`_PartialResultStore`(runner内部専用・キー接頭辞`michinoeki-partial-`固定) | **Constraint**: `_PartialResultStore`はmichinoeki専有の内部クラス。共通化 or 複製の判断が必要 |
| R8 リクエスト頻度制御 | `PageFetcher`が`ScrapingConfig`の`min_interval`を自動適用 | ギャップなし。ただしR4の補完で外部サービスを使う場合、そちらへの頻度制御は**Missing** |
| R9 廃止されたSA/PAの扱い | `merge_with_previous`はドメイン非依存(`source_url`ベース)で、そのままSA/PAにも正しく動作する | **Constraint**: michinoekiパッケージ内にあるため、06からのimportは依存方向が不自然。共通化 or 複製の判断が必要 |
| R10 動作ログの記録 | `logging_setup`+`runner`の集計ログパターン | パターン再利用で対応可(補完件数の集計のみ追加) |

### 複雑性シグナル

- 外部統合が2系統: 対象サイト(未選定)+座標補完手段(未選定)
- ドメイン固有の新規ロジック: 上り/下りの正規化(`Direction`列挙への写像)、上下線別施設の識別子設計(同名施設が上下で別Feature→`source_url`がマージキーとして機能するかはサイトURL構造次第)、所在都道府県の特定(路線単位サイトの場合は住所文字列からの都道府県導出が必要になる可能性)

### Research Needed(設計フェーズへ持ち越し)

1. **対象サイトの選定**: 全国のSA/PAを網羅する情報源。NEXCO 3社(東/中/西)でサイトが分かれている可能性が高く、複数サイト構成になる場合は一覧収集・レジューム・削除状態管理の単位に影響
2. **座標の提供状況**: 選定サイトが緯度経度を直接提供するか(05のような`data-lat`/`data-lng`埋め込みか、地図リンクからの抽出か、非提供か)
3. **座標補完手段の選定**(R4.2): 住所→座標の導出方法。候補の利用規約・精度・レート制限・オフライン可否の比較(候補例: 国土地理院ジオコーディングAPI等。詳細調査は設計フェーズ)
4. **所在都道府県の特定方法**(R3.6): サイトが都道府県情報を直接提供するか、住所文字列からの導出(`PREFECTURES`の日本語名前方一致等)が必要か
5. **上下線の表現と識別子**: 上り/下りが別ページ(別URL)か同一ページ内の区分か。マージキー(`source_url`)が上下線別Featureを一意に識別できるか
6. **座標補完の記録方法**(R4.4): ログのみで満たすか、GeoJSONプロパティに補完由来フラグを追加するか(後者は03スキーマ拡張が発生し、Adjacent expectationsの「追加拡張不要」前提が崩れる)

## 3. 実装アプローチ選択肢

### Option A: `michinoeki/`の汎用部分をそのまま流用(06から直接import)

`scope`・`merge`・`_PartialResultStore`を`sapa/`パッケージから`michinoeki`パッケージ越しにimportして使う。

- ✅ 変更ファイル最小・既存テストへの影響ゼロで最速
- ❌ `sapa → michinoeki`という兄弟パッケージ間依存が生まれ、「site固有パッケージ→共通層」の一方向依存規約を壊す
- ❌ `_PartialResultStore`は非公開(`_`接頭辞)かつキー接頭辞が`michinoeki-partial-`固定で、そのままでは流用不可

### Option B: `sapa/`パッケージを新設し、汎用ロジックも複製

`michinoeki/`と対称な`sapa/`(site_urls・listing・detail・merge・scope・runner・cli)を作り、`scope.py`・`merge.py`・部分結果ストアはコピーして保守する。

- ✅ パッケージ間依存が発生せず、各specの独立性が保たれる
- ✅ サイト構造の違い(路線単位一覧等)に合わせて自由に変形できる
- ❌ `REGIONS`(47都道府県の区分表)・削除状態遷移ロジックという「仕様そのもの」が二重管理になり、修正漏れリスク(05 research.mdが既に懸念として記録)

### Option C: 汎用部分を共通層へ昇格+`sapa/`新設(推奨候補)

確定的にドメイン非依存な`scope.py`(REGIONS・resolve_scope)・`merge.py`(merge_with_previous)・部分結果ストア(キー接頭辞をパラメータ化)を`geojson/`または`common/`へ移設し、`michinoeki/`は再exportまたはimport置換で追従。そのうえでサイト固有の`sapa/`(site_urls・listing・detail・runner・cli)を新設する。

- ✅ 05 research.mdの「06実装時に重複が判明した場合に共通化を検討」という留保を、判明した今回に解消する設計意図どおりの進め方
- ✅ 依存方向の規約(site固有→共通層)を維持
- ❌ 05の既存コード・テストにリファクタリングが波及(mergeのdocstringは道の駅前提の記述を含むため書き換えが必要)
- ❌ 移設先の選定(`common/`はGeoJSON型に依存しない層のため、`FacilityFeature`に依存するmergeは`geojson/`寄りが自然、等)という設計判断が増える

## 4. 工数・リスク評価

- **工数: L(1〜2週間)** — サイト固有実装(listing/detail)+座標補完という新規外部統合+共通化リファクタリング。R6/R8等の基盤流用部分はゼロ工数だが、対象サイト実測(research)と補完手段の検証が上乗せされる
- **リスク: Medium** — オーケストレーション・レジューム・削除状態管理は実証済みパターンの踏襲で低リスク。一方、対象サイト未選定(複数サイト構成の可能性)と座標補完(外部サービスの規約・精度・レート制限)が不確実性の中心。上下線識別子の設計を誤るとマージ(削除状態)が誤動作するため、サイト実測を設計フェーズの必須入力とすべき

## 5. 設計フェーズへの推奨事項

- **推奨アプローチ**: Option C(共通化+`sapa/`新設)を基本線とし、共通化対象は「06でも変更なしで使える」ことが実測で確認できたものに限定する(サイト構造次第でscope/mergeの前提が崩れる場合はOption Bへ後退)
- **設計で確定すべき主要判断**:
  1. 対象サイト(単一/複数)と一覧収集の単位(都道府県/路線)→ Research Needed 1・5
  2. 座標補完手段と、その頻度制御・失敗時挙動 → Research Needed 2・3
  3. マージキー(上下線別Featureの一意識別子)→ Research Needed 5
  4. 補完由来の記録方法(ログのみ or スキーマ拡張)→ Research Needed 6(スキーマ拡張を選ぶ場合は03の再検証が必要)
  5. 共通化の移設先とmichinoeki側の追従方法(再export or import置換)
- **要件へのフィードバック**: 現時点で要件の修正を要する矛盾は検出されず。ただしResearch Needed 1で対象サイトが複数になる場合、R2.3「失敗した範囲」の単位(都道府県か・サイトか)の解釈を設計で明確化すること
