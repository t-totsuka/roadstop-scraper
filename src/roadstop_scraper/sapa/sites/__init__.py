"""SA/PAサイトアダプタの共通契約(雛形)。

NEXCO東日本・中日本・西日本の3サイトの差異(URL構成・HTML構造・上り/下り等
の表記)を吸収するアダプタが実装すべき共通型・プロトコルをここへ定義する
(design.md「sapa.sites」節参照)。

実際の型定義(``SapaStub``・``SapaListingResult``・``SapaDetail``・
``SapaSite``プロトコル)と、上下線・名称正規化の共通ヘルパ、3アダプタの
登録順リスト(``ALL_SITES``)はタスク2.3・3.4で実装する。
"""
