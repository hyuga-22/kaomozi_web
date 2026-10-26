#
# キーボードの入力処理を格納するモジュールです
#


# キーボードから整数を入力して返す
def input_int(prompt):
    while True:
        num = input(prompt)
        if num.isdigit():   # 整数に変換できるか
            break
        else:
            print()
            print("[Error]：整数で入力してください！")
            print()
            
    return int(num)

# キーボードから入力したものが空であれば再入力させる
# 空でなければその内容を返す
def input_required(prompt):
    while True:
        str = input(prompt)
#        if str:   でも可
        if len(str.strip()) != 0:
            break          # 文字列の長さが0ではない=空ではない
        else:
            print()
            print("[Error]：必ず入力が必要な項目です！")
            print()
            
    return str.strip()



# キーボードからyまたはnを入力して返す
# True:yが入力された場合 False:nが入力された場合
def input_boolean(prompt):
    while True:
        str = input(f"{prompt} (y/n) ：")
        if str.lower() == "y":
            return True
        elif str.lower() == "n":
            return False
        




