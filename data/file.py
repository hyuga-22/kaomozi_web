import os
import json

# 顔文字データの保存先
KAOMOZI_PATH = os.path.join(os.path.dirname(__file__), "kaomozi.json")

# お気に入り顔文字データの保存先
FAVORITE_PATH = os.path.join(os.path.dirname(__file__), "favorite.json")


# お気に入りの保存先
path = os.path.join("favorite")
if not os.path.exists(path):
    os.makedirs(path)

# 顔文字のデータのJSON読み込み
def load_kaomozi():
    if not os.path.exists(KAOMOZI_PATH):
        return {}
    with open(KAOMOZI_PATH, "r", encoding="utf-8") as file:
        return json.load(file)

# 顔文字データのJSON保存
def save_kaomozi(data):
    with open(KAOMOZI_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

# お気に入りの顔文字のデータのJSON読み込み
def load_favorite():
    if not os.path.exists(FAVORITE_PATH):
        return {"favorites": []}

    with open(FAVORITE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 万が一リスト形式だった場合も修正
    if isinstance(data, list):
        return {"favorites": data}

    return data

    
# お気に入りの顔文字のデータのJSON保存
def save_favorite_json(name=None, overwrite_list=None):
    # overwrite_list が渡された場合は丸ごと保存
    if overwrite_list is not None:
        with open(FAVORITE_PATH, "w", encoding="utf-8") as f:
            json.dump({"favorites": overwrite_list}, f, ensure_ascii=False, indent=4)
        return

    # 通常の追加処理
    data = load_favorite()
    favorites = data["favorites"]

    if name not in favorites:
        favorites.append(name)

    with open(FAVORITE_PATH, "w", encoding="utf-8") as f:
        json.dump({"favorites": favorites}, f, ensure_ascii=False, indent=4)






# 登録機能
def add_kaomoji(name, kaomoji):
    data = load_kaomozi()
    data[name] = kaomoji
    save_kaomozi(data)

# 削除機能
def delete_kaomoji(name):
    data = load_kaomozi()
    if name in data:
        del data[name]
        save_kaomozi(data)
        return True
    return False

# 顔文字検索機能
def search_kaomoji(keyword):
    data = load_kaomozi()
    result = {}

    for name, kaomoji in data.items():
        if keyword in name or keyword in kaomoji:
            result[name] = kaomoji

    return result

# お気に入り削除機能
def delete_favorite(index):
    data = load_favorite()
    favorites = data["favorites"]

    # index は 0 始まりで扱う
    if 0 <= index < len(favorites):
        removed = favorites.pop(index)

        with open(FAVORITE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        return removed
    else:
        return None



# # お気に入りをファイルに保存
# # favorite_kaomozi：保存したい顔文字の文字列
# def save_favorite(favorite_kaomozi):
#     """ファイルは自動的に閉じる　追記モード　パスを指定"""
#     with open(os.path.join(path, "favorite.txt"), "a", encoding="utf-8") as file:
#         """顔文字追加後に改行"""
#         file.write(favorite_kaomozi + "\n")

# # お気に入りをファイルから読み込み
# def load_favorite():
#     try:
#         """ファイルは自動的に閉じる　読み取りモード　パスを指定"""
#         with open(os.path.join(path, "favorite.txt"), "r", encoding="utf-8") as file:
#             """ファイルの各行をリストとして返す"""
#             return file.readlines()
#     # ファイルがなかった時、print文を表示
#     except FileNotFoundError:
#         print("チャットボット：まだお気に入りはありません！")

# # お気に入りの表示機能
# def menu_favorite():
#     favorites = load_favorite()
#     if favorites:
#         print()
#         print("お気に入りの顔文字はこちらです！")
#         print("----------------------------------------------------------------")
#         for favorite in favorites:
#             print(favorite.strip())
#         print("----------------------------------------------------------------")
#     else:
#         print("お気に入りの顔文字はまだありません。")
