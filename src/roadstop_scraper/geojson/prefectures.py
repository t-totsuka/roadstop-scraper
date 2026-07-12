"""47都道府県の番号・ローマ字名・日本語名の対応表と参照関数。

全国地方公共団体コード準拠のゼロ埋め2桁コード(``01``〜``47``)を鍵として、
出力ファイル名に使う小文字ローマ字名と日本語名を引く。対応表は本モジュールが
唯一の正であり、他モジュールでの重複定義を禁止する。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PREFECTURES", "Prefecture", "UnknownPrefectureError", "find_prefecture"]


class UnknownPrefectureError(ValueError):
    """対応表に存在しない都道府県コードが指定された場合に送出される。"""


@dataclass(frozen=True)
class Prefecture:
    """都道府県1件の対応情報。"""

    code: str
    """ゼロ埋め2桁コード("01"〜"47")。"""

    romaji: str
    """小文字ローマ字名(例: "hokkaido")。出力ファイル名の構成要素になる。"""

    name_ja: str
    """日本語名(例: "北海道")。"""


PREFECTURES: tuple[Prefecture, ...] = (
    Prefecture("01", "hokkaido", "北海道"),
    Prefecture("02", "aomori", "青森県"),
    Prefecture("03", "iwate", "岩手県"),
    Prefecture("04", "miyagi", "宮城県"),
    Prefecture("05", "akita", "秋田県"),
    Prefecture("06", "yamagata", "山形県"),
    Prefecture("07", "fukushima", "福島県"),
    Prefecture("08", "ibaraki", "茨城県"),
    Prefecture("09", "tochigi", "栃木県"),
    Prefecture("10", "gunma", "群馬県"),
    Prefecture("11", "saitama", "埼玉県"),
    Prefecture("12", "chiba", "千葉県"),
    Prefecture("13", "tokyo", "東京都"),
    Prefecture("14", "kanagawa", "神奈川県"),
    Prefecture("15", "niigata", "新潟県"),
    Prefecture("16", "toyama", "富山県"),
    Prefecture("17", "ishikawa", "石川県"),
    Prefecture("18", "fukui", "福井県"),
    Prefecture("19", "yamanashi", "山梨県"),
    Prefecture("20", "nagano", "長野県"),
    Prefecture("21", "gifu", "岐阜県"),
    Prefecture("22", "shizuoka", "静岡県"),
    Prefecture("23", "aichi", "愛知県"),
    Prefecture("24", "mie", "三重県"),
    Prefecture("25", "shiga", "滋賀県"),
    Prefecture("26", "kyoto", "京都府"),
    Prefecture("27", "osaka", "大阪府"),
    Prefecture("28", "hyogo", "兵庫県"),
    Prefecture("29", "nara", "奈良県"),
    Prefecture("30", "wakayama", "和歌山県"),
    Prefecture("31", "tottori", "鳥取県"),
    Prefecture("32", "shimane", "島根県"),
    Prefecture("33", "okayama", "岡山県"),
    Prefecture("34", "hiroshima", "広島県"),
    Prefecture("35", "yamaguchi", "山口県"),
    Prefecture("36", "tokushima", "徳島県"),
    Prefecture("37", "kagawa", "香川県"),
    Prefecture("38", "ehime", "愛媛県"),
    Prefecture("39", "kochi", "高知県"),
    Prefecture("40", "fukuoka", "福岡県"),
    Prefecture("41", "saga", "佐賀県"),
    Prefecture("42", "nagasaki", "長崎県"),
    Prefecture("43", "kumamoto", "熊本県"),
    Prefecture("44", "oita", "大分県"),
    Prefecture("45", "miyazaki", "宮崎県"),
    Prefecture("46", "kagoshima", "鹿児島県"),
    Prefecture("47", "okinawa", "沖縄県"),
)
"""47件・コード昇順の対応表。"""

# コードでの参照はO(1)で行えるよう、モジュール読み込み時に索引を構築する
_PREFECTURES_BY_CODE: dict[str, Prefecture] = {
    prefecture.code: prefecture for prefecture in PREFECTURES
}


def find_prefecture(code: str) -> Prefecture:
    """``code`` に対応する :class:`Prefecture` を返す。

    対応表に存在しないコードは :class:`UnknownPrefectureError` を送出する。
    """
    try:
        return _PREFECTURES_BY_CODE[code]
    except KeyError:
        raise UnknownPrefectureError(
            f"未知の都道府県コードです: {code!r}(有効な値は '01'〜'47')"
        ) from None
