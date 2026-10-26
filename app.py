from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask import send_file
from datetime import datetime
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import os
import zipfile
import threading
import tempfile
from functools import wraps


load_dotenv()  # .env を読み込む


app = Flask(__name__)

# Render などのプロキシの背後で動かすとき、実際のアクセス元IPを使うための設定。
# （レート制限が全員まとめて1人扱いにならないようにする）
# 手元（プロキシなし）では設定しない。環境変数 BEHIND_PROXY=1 のときだけ有効。
if os.environ.get("BEHIND_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],  # 全体のデフォルト制限はなし。個別のルートだけ制限する
    storage_uri="memory://",  # メモリ保存
)

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # アップロード上限を5MBに制限


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

def login_required_api(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"status": "error", "message": "not logged in"}), 403
        return f(*args, **kwargs)
    return decorated


file_lock = threading.Lock()

def atomic_write_json(path, data):
    """
    一時ファイルに書き込んでから os.replace() で置き換えることで、
    書き込み途中のクラッシュによるファイル破損を防ぐ。
    """
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "kaomozi.json")
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
FAVORITE_PATH = os.path.join(DATA_DIR, "favorite.json")

ORDER_PATH = os.path.join(DATA_DIR, "order.json")
ADMIN_PATH = os.path.join(DATA_DIR, "admin.json")
REQUEST_PATH = os.path.join(DATA_DIR, "request.json")
BACKUP_ZIP_PATH = os.path.join(DATA_DIR, "backup.zip")
BACKUP_INFO_PATH = os.path.join(DATA_DIR, "backup_info.json")


@app.context_processor
def inject_login_status():
    return dict(logged_in=session.get("logged_in", False))


def load_kaomozi():
    # 辞書ファイルが存在しない場合は空の辞書を返す
    if not os.path.exists(DATA_PATH):
        print("Warning: 辞書ファイルが存在しません。")
        return {}

    try:
        # 辞書ファイルを読み込む
        with file_lock:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)

    except json.JSONDecodeError:
        # JSON が壊れている場合
        print("Error: 辞書ファイルの JSON 形式が壊れています。")
        return {}

    except Exception as e:
        # その他の予期しないエラー
        print(f"Error: 辞書読み込み中に予期しないエラーが発生しました: {e}")
        return {}



def save_kaomozi(data):
    with file_lock:
        atomic_write_json(DATA_PATH, data)

def load_favorite():
    if not os.path.exists(FAVORITE_PATH):
        return {"favorites": []}

    with file_lock:
        with open(FAVORITE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

    # 古い形式（辞書形式）だった場合は変換
    if isinstance(data, dict) and "favorites" not in data:
        # 旧形式 {"んー": "(顔文字)", ...} → 名前だけ抽出
        return {"favorites": list(data.keys())}

    # リスト形式だった場合（CLI の古い形式）
    if isinstance(data, list):
        return {"favorites": data}

    return data


def save_favorite(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with file_lock:
        atomic_write_json(FAVORITE_PATH, data)


# -----------------------------
# 並び替えJSON
# -----------------------------
def load_order():
    if not os.path.exists(ORDER_PATH):
        data = load_kaomozi()
        order = list(data.keys()) # 初期順は登録順
        with file_lock:
            atomic_write_json(ORDER_PATH, {"order": order})

    # 読み込み
    with file_lock:
        with open(ORDER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


def save_order(data):
    with file_lock:
        atomic_write_json(ORDER_PATH, data)


# -----------------------------
# メインメニュー
# -----------------------------
@app.route("/")
def menu():
    return render_template("menu.html")

# 顔文字リストの取得
@app.route("/list")
def list_page():
    data = load_kaomozi()
    order = load_order()["order"]  # ← 並び順を読み込む

    # 並び順に従って並べ替えた辞書を作る
    sorted_data = {name: data[name] for name in order if name in data}

    # 通常表示
    return render_template("list.html", kaomozi=sorted_data)



# -----------------------------
# 顔文字の登録
# -----------------------------

@app.route("/add", methods=["GET", "POST"])
@login_required
def add_page():
    data = load_kaomozi()

    if request.method == "POST":
        name = request.form["name"].strip()
        kaomozi = request.form["kaomozi"].strip()

        # 空欄チェック
        if not name or not kaomozi:
            return render_template("add.html", error="名前と顔文字は必須です。")

        # 重複チェック
        if name in data:
            return render_template("add.html", error="その名前の顔文字はすでに登録されています。")

        # 禁止文字チェック（CLI版と同じ）
        NG = [" ", "　"]  # 空白禁止など
        if any(ng in name for ng in NG):
            return render_template("add.html", error="名前に空白は使えません。")

        # 登録処理（kaomozi.json）
        data[name] = kaomozi
        save_kaomozi(data)

        # order.json にも登録する
        order_data = load_order()
        order = order_data["order"]

        # 新しい名前が order.json にない場合は追加
        if name not in order:
            order.append(name)

        save_order({"order": order})


        return render_template("add.html", success="登録しました！")

    return render_template("add.html")



# 顔文字の登録確認
@app.route("/confirm", methods=["POST"])
@login_required
def confirm():

    name = request.form.get("name", "")
    face = request.form.get("face", "")

    if not name or not face:
        return redirect(url_for("add_page"))

    data = load_kaomozi()

    # /add と同様、既存の名前との重複はここでも防いでおく
    if name in data:
        return redirect(url_for("add_page"))

    # 保存処理（kaomozi.json）
    data[name] = face
    save_kaomozi(data)

    # order.json にも同期する（/add と同じ処理）
    order_data = load_order()
    order = order_data["order"]

    if name not in order:
        order.append(name)

    save_order({"order": order})
    flash(f"「{name}」を登録しました。")

    return redirect(url_for("menu"))


# -----------------------------
# お気に入り追加
# -----------------------------
@app.route("/favorite/add/<name>", methods=["POST"])
@login_required
def favorite_add(name):

    data = load_kaomozi()          # 顔文字辞書
    fav = load_favorite()          # お気に入り
    favorites = fav["favorites"]

    # 辞書に存在しない名前は追加不可（安全対策として...）
    if name not in data:
        flash("その名前の顔文字は存在しません。")
        return redirect(url_for("list_page"))

    # 顔文字を取得
    face = data[name]              

    # 重複チェック
    if name in favorites:
        flash(f"「{name} : {face}」はすでにお気に入りに登録されています！")
        return redirect(url_for("list_page"))

    # 顔文字追加処理
    favorites.append(name)
    save_favorite({"favorites": favorites})

    # 追加成功メッセージ（名前 + 顔文字）
    flash(f"「{name} : {face}」をお気に入りに追加しました！")

    # 戻り先は顔文字一覧ページ
    return redirect(url_for("list_page"))




# -----------------------------
# お気に入りページ
# -----------------------------
@app.route("/favorite")
@login_required
def favorite_page():
    fav = load_favorite()
    data = load_kaomozi()

    # favorites の中に「存在しない名前」があれば除外する
    valid_favorites = [name for name in fav["favorites"] if name in data]

    # もし除外が発生したら favorite.json を更新する
    if valid_favorites != fav["favorites"]:
        save_favorite({"favorites": valid_favorites})

    return render_template("favorite.html", favorite={"favorites": valid_favorites}, kaomozi=data)


# -----------------------------
# お気に入り削除
# -----------------------------

@app.route("/favorite/confirm/<name>")
@login_required
def favorite_confirm(name):
    fav = load_favorite()
    data = load_kaomozi()

    # name が favorites に存在しない、または kaomozi.json 側に既に存在しない場合の安全対策
    if name not in fav["favorites"] or name not in data:
        return redirect(url_for("favorite_page"))

    return render_template("favorite_confirm.html", name=name, kaomozi=data[name])

@app.route("/favorite/remove/<name>", methods=["POST"])
@login_required
def favorite_remove(name):
    
    fav = load_favorite()
    favorites = fav["favorites"]

    # 存在しない名前でも remove しようとしてエラーにならないようにする
    if name in favorites:
        favorites.remove(name)
        flash(f"「{name}」をお気に入りから削除しました。")

    save_favorite({"favorites": favorites})
    return redirect(url_for("favorite_page"))




# -----------------------------
# 顔文字の削除
# -----------------------------
@app.route("/delete_select", methods=["GET", "POST"])
@login_required
def delete_select():
    data = load_kaomozi()
    results = {}

    if request.method == "POST":
        keyword = request.form.get("keyword", "").strip()

        # 空欄チェック
        if not keyword:
            return render_template("delete_select.html", error="検索ワードを入力してください。", results={}, all_data=data)

        # スペースのみ禁止
        if keyword.replace(" ", "").replace("　", "") == "":
            return render_template("delete_select.html", error="スペースのみの検索はできません。", results={}, all_data=data)

        # 長すぎる検索ワード禁止
        if len(keyword) > 100:
            return render_template("delete_select.html", error="検索ワードが長すぎます。（100文字以内）", results={}, all_data=data)

        # 検索実行
        results = {k: v for k, v in data.items() if keyword in k or keyword in v}

        if not results:
            return render_template("delete_select.html", error="該当する顔文字がありません。", results={}, all_data=data)

    return render_template("delete_select.html", results=results, all_data=data)




# -----------------------------
# 顔文字編集
# -----------------------------

@app.route("/edit_select", methods=["GET", "POST"])
@login_required
def edit_select():
    data = load_kaomozi()
    results = data  # 初期表示は全件

    if request.method == "POST":
        keyword = request.form.get("keyword", "")
        results = {}

        for name, face in data.items():
            if keyword in name or keyword in face:
                results[name] = face

    return render_template("edit_select.html", results=results)

@app.route("/edit/<name>", methods=["GET", "POST"])
@login_required
def edit_page(name):
    data = load_kaomozi()

    # 存在しない名前なら一覧に戻す
    if name not in data:
        return redirect(url_for("edit_select"))

    old_face = data[name]

    if request.method == "POST":
        new_name = request.form.get("new_name", "").strip()
        new_face = request.form.get("new_face", "").strip()

        # 空欄の場合は「変更なし」と扱う
        if new_name == "":
            new_name = name
        if new_face == "":
            new_face = old_face

        # 名前を変更する場合、既存の別の顔文字と衝突していないかチェック
        if new_name != name and new_name in data:
            return render_template(
                "edit_page.html",
                name=name,
                face=old_face,
                error=f"「{new_name}」という名前はすでに使われています。"
            )

        # edit_confirm に渡す
        return render_template(
            "edit_confirm.html",
            old_name=name,
            old_face=old_face,
            new_name=new_name,
            new_face=new_face
        )

    # GET の場合は編集ページを表示
    return render_template(
        "edit_page.html",
        name=name,
        face=old_face
    )

@app.route("/edit_apply/<old_name>", methods=["POST"])
@login_required
def edit_apply(old_name):
    
    # 新しい値を取得
    new_name = request.form.get("new_name")
    new_face = request.form.get("new_face")

    # 顔文字辞書を読み込み
    data = load_kaomozi()

    # old_name が存在しない場合は編集選択へ戻す
    if old_name not in data:
        return redirect(url_for("edit_select"))

    # ① kaomozi.json の更新
    # 名前が変わる場合（キーを変更）
    if new_name != old_name:
        if new_name in data:
        # 想定外の衝突（edit_pageのチェックをすり抜けた場合の保険）
            return redirect(url_for("edit_select"))
        # 新しいキーを作成
        data[new_name] = new_face
        # 古いキーを削除
        del data[old_name]
    else:
        # 名前が変わらない場合は値だけ更新
        data[old_name] = new_face

    # 保存
    save_kaomozi(data)
    flash("編集内容を保存しました。")

    # ② favorite.json の整合性
    favorites = load_favorite()

    if new_name != old_name:
        updated = [new_name if item == old_name else item for item in favorites["favorites"]]
        favorites["favorites"] = updated
        save_favorite(favorites)

    # ③ order.json の整合性（追加）

    order_data = load_order()
    order = order_data["order"]

    if new_name != old_name:
        new_order = [new_name if item == old_name else item for item in order]
        save_order({"order": new_order})

    # ④ 編集完了 → 一覧へ戻す
    return redirect(url_for("list_page"))







@app.route("/delete_confirm/<name>")
@login_required
def delete_confirm(name):
    data = load_kaomozi()

    # 存在チェック
    if name not in data:
        return redirect(url_for("delete_select"))

    return render_template("delete_confirm.html", name=name, face=data[name])


@app.route("/delete_remove/<name>", methods=["POST"])
@login_required
def delete_remove(name):
    
    data = load_kaomozi()

    # 存在チェック
    if name in data:
        del data[name]
        save_kaomozi(data)
        flash(f"「{name}」を削除しました。")

    # お気に入りからも自動除外
    fav = load_favorite()
    favorites = fav["favorites"]
    if name in favorites:
        favorites.remove(name)
        save_favorite({"favorites": favorites})

    return redirect(url_for("delete_select"))


# -----------------------------
# バックアップ
# -----------------------------

@app.route("/backup_page")
@login_required
def backup_page():
    backup_info = load_backup_info()
    return render_template("backup.html", backup_info=backup_info)

@app.route("/backup", methods=["POST"])  # ← ここを POST に変更
@limiter.limit("5 per minute")
@login_required
def backup():
    
    # PINチェック
    pin = request.form.get("pin", "")
    if not check_pin(pin):
        return render_pin_error("/backup_page")


    with zipfile.ZipFile(BACKUP_ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(DATA_PATH, arcname="kaomozi.json")
        zipf.write(ORDER_PATH, arcname="order.json")
        zipf.write(FAVORITE_PATH, arcname="favorite.json")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_backup_info(now)

    return send_file(BACKUP_ZIP_PATH, as_attachment=True)

def load_backup_info():
    with file_lock:
        if not os.path.exists(BACKUP_INFO_PATH):
            return {"last_backup": None}

        with open(BACKUP_INFO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)



def save_backup_info(dt):
    with file_lock:
        atomic_write_json(BACKUP_INFO_PATH, {"last_backup": dt})

# バックアップから復元
@app.route("/restore_page")
@login_required
def restore_page():
    return render_template("restore.html")

@app.route("/restore_complete")
def restore_complete():
    return "<h1>復元が完了しました！</h1><a href='/'>メニューに戻る</a>"

# 復元
@app.route("/restore", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def restore():
    
    pin = request.form.get("pin", "")
    if not check_pin(pin):
        return render_pin_error("/restore_page")

    file = request.files.get("zipfile")
    if not file:
        return "ZIPファイルが選択されていません", 400

    zip_path = os.path.join(DATA_DIR, "upload_restore.zip")
    file.save(zip_path)

    # 復元を許可するファイルはこの3つだけ（ホワイトリスト）
    ALLOWED_RESTORE_FILES = {
        "restore_kaomozi": "kaomozi.json",
        "restore_order": "order.json",
        "restore_favorite": "favorite.json",
    }

    try:
        with zipfile.ZipFile(zip_path, "r") as zipf:
            for form_key, filename in ALLOWED_RESTORE_FILES.items():
                if form_key in request.form:
                    ok = safe_extract(zipf, filename, DATA_DIR)
                    if not ok:
                        print(f"Warning: {filename} の展開をスキップしました（不正 or 未検出）")
    except zipfile.BadZipFile:
        return "ZIPファイルが壊れています", 400
    finally:
        # 一時ファイルは処理後に削除しておく
        if os.path.exists(zip_path):
            os.remove(zip_path)

    return redirect(url_for("restore_complete"))

def safe_extract(zipf, member_name, extract_to_dir):
    """
    ZIP内の指定ファイルを、extract_to_dir の外に出ないことを検証した上で展開する。
    条件を満たさない場合は展開せず False を返す。
    """
    # ZIP内にファイルが存在するか
    if member_name not in zipf.namelist():
        return False

    # ZipInfo を取得し、シンボリックリンクやディレクトリでないことを確認
    info = zipf.getinfo(member_name)
    if info.is_dir():
        return False

    # 展開後の絶対パスを計算し、想定ディレクトリの配下に収まっているか検証
    target_path = os.path.abspath(os.path.join(extract_to_dir, member_name))
    base_path = os.path.abspath(extract_to_dir)

    if not target_path.startswith(base_path + os.sep) and target_path != base_path:
        # ../ などで外に出ようとしている＝不正
        return False

    # ここまで通れば安全に展開
    zipf.extract(member_name, extract_to_dir)
    return True


# バックアップPIN
PIN_CODE = os.environ.get("PIN_CODE")

if not PIN_CODE:
    raise RuntimeError("環境変数 PIN_CODE が設定されていません。.env を確認してください。")

def check_pin(input_pin: str) -> bool:
    return input_pin == PIN_CODE

def render_pin_error(return_url):
    return render_template("pin_error.html", return_url=return_url)




# 並び替え保存（顔文字一覧）
@app.route("/list/reorder", methods=["POST"])
@login_required_api
def list_reorder():

    try:
        data = request.get_json()
        new_order = data.get("order", [])

        order_data = {"order": new_order}
        save_order(order_data)

        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"Error: 並び替え保存中にエラーが発生しました: {e}")
        return jsonify({"status": "error", "message": "save failed"}), 500




# 並び替え保存（お気に入り）
@app.route("/favorite/reorder", methods=["POST"])
@login_required_api
def favorite_reorder():

    try:
        data = request.get_json()
        new_order = data.get("order", [])

        favorites = load_favorite()
        favorites["favorites"] = new_order
        save_favorite(favorites)

        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"Error: お気に入り並び替え保存中にエラーが発生しました: {e}")
        return jsonify({"status": "error", "message": "save failed"}), 500


# -----------------------------
# ログイン処理
# -----------------------------
app.secret_key = os.environ.get("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("環境変数 SECRET_KEY が設定されていません。.env を確認してください。")

# ログインページ（GET）
@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")


# ログイン処理（POST）
@app.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    username = request.form.get("username")
    password = request.form.get("password")

    # admin.json存在チェック
    if not os.path.exists(ADMIN_PATH):
        return render_template("login.html", error="管理者情報が見つかりません。")

    # admin.json を読み込む
    with open(ADMIN_PATH, "r", encoding="utf-8") as f:
        admin_data = json.load(f)

    # ユーザー名が一致するか
    if username != admin_data["username"]:
        return render_template("login.html", error="ユーザー名、またはパスワードが違います")

    # パスワード（ハッシュ）と照合
    if not check_password_hash(admin_data["password"], password):
        return render_template("login.html", error="ユーザー名、またはパスワードが違います")

    # ログイン成功
    session["logged_in"] = True
    return redirect("/")  # 管理者メニューへ遷移（後で作る）



# ログアウト処理
@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/login")

# 一般ユーザお気に入り
@app.route("/favorite_local")
def favorite_local():
    return render_template("favorite_local.html")

# 一般ユーザバックアップ
@app.route("/backup_local")
def favorite_local_backup():
    return render_template("backup_local.html")

# 一般ユーザ バックアップ復元(マージ)
@app.route("/restore_local")
def favorite_local_restore():
    return render_template("restore_local.html")


# -----------------------------
# リクエストページ 
# -----------------------------
def load_requests():
    with file_lock:
        if not os.path.exists(REQUEST_PATH):
            return []
        with open(REQUEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


def save_requests(data):
    with file_lock:
        atomic_write_json(REQUEST_PATH, data)


@app.route("/request_page")
def request_page():
    return render_template("request_page.html")


@app.route("/send_request", methods=["POST"])
@limiter.limit("5 per minute")  
def send_request():
    name = request.form.get("name", "").strip()
    kaomozi = request.form.get("kaomozi", "").strip()
    comment = request.form.get("comment", "").strip()
    rating = request.form.get("rating", "").strip()

    # すべて空欄の場合は受け付けない
    if not name and not kaomozi and not comment and not rating:
        return render_template(
            "request_page.html",
            error="いずれか1項目は入力してください！"
        )

    # 保存するデータ構造
    entry = {
        "name": name,
        "kaomozi": kaomozi,
        "comment": comment,
        "rating": rating,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # 保存
    data = load_requests()
    data.append(entry)
    save_requests(data)

    return "送信しました！<br><a href='/'>メニューに戻る</a>"


@app.route("/request_admin")
@login_required
def request_admin():

    # ログイン済みなら PIN入力ページへ誘導
    return redirect("/request_pin")

# pin入力
@app.route("/request_pin")
@login_required
def request_pin():
    return render_template("request_pin.html")


@app.route("/request_pin_check", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def request_pin_check():

    pin = request.form.get("pin", "")

    if not check_pin(pin):
        return render_pin_error("/request_pin")

    # PINが正しければフラグをセット
    session["request_admin_pin_ok"] = True

    return redirect("/request_admin_real")





@app.route("/request_admin_real")
@login_required
def request_admin_real():

    # PINチェックがまだなら PIN入力ページへ戻す
    if not session.get("request_admin_pin_ok"):
        return redirect("/request_pin")

    requests = load_requests()

    return render_template("request_admin.html", requests=requests)






@app.route("/delete_request/<int:index>", methods=["POST"])
@login_required
def delete_request(index):

    if not session.get("request_admin_pin_ok"):
        return redirect("/request_pin")

    # JSON読み込み
    data = load_requests()

    # indexが範囲内なら削除
    if 0 <= index < len(data):
        data.pop(index)
        save_requests(data)

    # 削除後に管理者ページへ戻す
    return redirect("/request_admin_real")


# -----------------------------
# エラーハンドル
# -----------------------------
@app.errorhandler(429)
def rate_limit_exceeded(e):
    return "試行回数が多すぎます。しばらく時間をおいて再度お試しください。", 429

@app.errorhandler(413)
def file_too_large(e):
    return "ファイルサイズが大きすぎます（上限5MB）", 413



if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "False") == "True"
    app.run(debug=debug_mode)
    app.run(host='0.0.0.0', port=5000, debug=True)