from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from rembg import remove, new_session
from PIL import Image, ImageFilter
import numpy as np
from scipy.ndimage import binary_erosion, binary_dilation, gaussian_filter
import io
import os
import zipfile

os.environ["ONNXRUNTIME_PROVIDERS"] = "CPUExecutionProvider"

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

print("Carregando modelo de IA... aguarde.")
session = new_session("u2net")
print("Modelo carregado! Servidor pronto.")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}

# ─── Constantes de composição ─────────────────────────────────
CANVAS = 1800

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ─── Remoção de fundo + limpeza de sombra ────────────────────
def remove_bg(image_bytes):
    """Remove o fundo com rembg e depois aplica limpeza de sombra/semitransparência."""
    image = Image.open(io.BytesIO(image_bytes))
    if max(image.size) > 1200:
        image.thumbnail((1200, 1200), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    raw = remove(buf.getvalue(), session=session)
    return clean_shadow(raw)

def clean_shadow(rgba_bytes, alpha_threshold=30, erode_px=1, feather_radius=1.2):
    """
    Remove sombras e semitransparências residuais preservando detalhes finos
    (grades, furos, malhas) — abordagem por morfologia binária.

    Pipeline:
    1. Threshold inicial SUAVE: elimina apenas pixels quase invisíveis (alpha < 30).
       Um threshold baixo preserva os pixels de borda que formam as grades.
    2. Erosão binária leve: encolhe a máscara 1px para separar sombras grudadas.
    3. Dilatação binária: restaura o tamanho original sem reabsorver os buracos
       que foram abertos pela erosão — é aqui que os furos/grades são preservados.
    4. Gaussian blur MUITO leve na borda para suavizar serrilhado sem fechar furos.
    5. Threshold final para reafirmar a máscara limpa.

    Por que isso é melhor que threshold duro + blur (abordagem anterior):
    - O threshold duro (≥128) cortava pixels de borda válidos das grades.
    - O GaussianBlur espalhava pixels opacos para dentro dos furos, fechando-os.
    - A morfologia trabalha com a ESTRUTURA da máscara, não com os valores de alpha,
      portanto respeita naturalmente os buracos internos do objeto.
    """
    img  = Image.open(io.BytesIO(rgba_bytes)).convert("RGBA")
    data = np.array(img)
    alpha = data[:, :, 3].astype(np.float32)

    # ── 1. Threshold suave: descarta apenas sombras muito transparentes ──────
    mask = (alpha >= alpha_threshold)          # bool array

    # ── 2. Erosão leve: separa halos e sombras grudadas na borda ─────────────
    struct = np.ones((erode_px * 2 + 1, erode_px * 2 + 1), dtype=bool)
    mask_eroded = binary_erosion(mask, structure=struct)

    # ── 3. Dilatação: restaura o tamanho mas os furos internos permanecem ────
    mask_dilated = binary_dilation(mask_eroded, structure=struct)

    # ── 4. Gaussian blur leve para suavizar a borda (sem fechar furos) ───────
    mask_float = mask_dilated.astype(np.float32)
    mask_smooth = gaussian_filter(mask_float, sigma=feather_radius)

    # ── 5. Threshold final suave para reafirmar bordas limpas ────────────────
    final_alpha = np.clip(mask_smooth * 255, 0, 255).astype(np.uint8)

    result = img.copy()
    result.putalpha(Image.fromarray(final_alpha, mode='L'))

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()

def to_white_bg(rgba_bytes):
    img   = Image.open(io.BytesIO(rgba_bytes)).convert("RGBA")
    fundo = Image.new("RGBA", img.size, (255, 255, 255, 255))
    fundo.paste(img, mask=img.split()[3])
    return fundo.convert("RGBA")

# ─── Helpers de composição ────────────────────────────────────
def resize_to_scale(img, canvas_size, escala):
    img  = img.copy()
    w, h = img.size
    if w == 0 or h == 0:
        return img
    max_dim = int(canvas_size * escala)
    ratio   = min(max_dim / w, max_dim / h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

def paste_rgba(canvas, img, x, y):
    if img.mode == "RGBA":
        canvas.paste(img, (x, y), img.split()[3])
    else:
        canvas.paste(img, (x, y))

def calc_free_pos(canvas_size, img_w, img_h, pos_x, pos_y):
    cx = canvas_size / 2 + (pos_x / 100.0) * (canvas_size / 2)
    cy = canvas_size / 2 + (pos_y / 100.0) * (canvas_size / 2)
    left = int(cx - img_w / 2)
    top  = int(cy - img_h / 2)
    return left, top

# ─── Canvas: produto isolado ──────────────────────────────────
def make_canvas_produto(produto_img, escala_produto=0.90):
    canvas  = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 255))
    produto = resize_to_scale(produto_img.convert("RGBA"), CANVAS, escala_produto)
    px = (CANVAS - produto.width)  // 2
    py = (CANVAS - produto.height) // 2
    paste_rgba(canvas, produto, px, py)
    fundo = Image.new("RGB", (CANVAS, CANVAS), (255, 255, 255))
    fundo.paste(canvas, mask=canvas.split()[3])
    return fundo

# ─── Canvas: produto + elemento secundário ───────────────────
def make_canvas_com_elemento(produto_img, elemento_img,
                              escala_produto=0.90, escala_elemento=0.40,
                              pos_x=0, pos_y=0):
    canvas  = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 255))
    produto = resize_to_scale(produto_img.convert("RGBA"), CANVAS, escala_produto)
    px = (CANVAS - produto.width)  // 2
    py = (CANVAS - produto.height) // 2
    paste_rgba(canvas, produto, px, py)
    elem  = resize_to_scale(elemento_img.convert("RGBA"), CANVAS, escala_elemento)
    ex, ey = calc_free_pos(CANVAS, elem.width, elem.height, pos_x, pos_y)
    paste_rgba(canvas, elem, ex, ey)
    fundo = Image.new("RGB", (CANVAS, CANVAS), (255, 255, 255))
    fundo.paste(canvas, mask=canvas.split()[3])
    return fundo

# ─── Helpers de parse ─────────────────────────────────────────
def parse_float_pct(val, default, lo=0.10, hi=1.50):
    try:
        v = float(val) / 100.0
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return default

def parse_int_pos(val, default=0, lo=-100, hi=100):
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return default

# ─── Rotas ────────────────────────────────────────────────────
@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/remove-bg", methods=["POST"])
def remove_background():
    fundo_branco  = request.form.get("fundo_branco",  "false").lower() == "true"
    usar_caixinha = request.form.get("usar_caixinha", "false").lower() == "true"
    usar_veiculo  = request.form.get("usar_veiculo",  "false").lower() == "true"

    idx_caixinha = parse_int_pos(request.form.get("idx_caixinha", "-1"), -1, -1, 9999)
    idx_veiculo  = parse_int_pos(request.form.get("idx_veiculo",  "-1"), -1, -1, 9999)

    escala_produto  = parse_float_pct(request.form.get("escala_produto",  "90"),  0.90)
    escala_caixinha = parse_float_pct(request.form.get("escala_caixinha", "40"),  0.40)
    escala_veiculo  = parse_float_pct(request.form.get("escala_veiculo",  "40"),  0.40)

    pos_box_x     = parse_int_pos(request.form.get("pos_box_x",     "0"))
    pos_box_y     = parse_int_pos(request.form.get("pos_box_y",     "0"))
    pos_vehicle_x = parse_int_pos(request.form.get("pos_vehicle_x", "0"))
    pos_vehicle_y = parse_int_pos(request.form.get("pos_vehicle_y", "0"))

    print(f"[DEBUG] prod={escala_produto:.2f} "
          f"caixa={escala_caixinha:.2f} pos=({pos_box_x},{pos_box_y}) "
          f"veiculo={escala_veiculo:.2f} pos=({pos_vehicle_x},{pos_vehicle_y})")

    produtos_files = request.files.getlist("produtos")
    if not produtos_files:
        return jsonify({"error": "Nenhuma imagem enviada."}), 400

    produtos_bytes = []
    for f in produtos_files:
        if not allowed_file(f.filename):
            return jsonify({"error": f"Formato não suportado: {f.filename}"}), 400
        produtos_bytes.append((f.filename, f.read()))

    caixinha_bytes = None
    veiculo_bytes  = None
    if usar_caixinha and "caixinha" in request.files:
        caixinha_bytes = request.files["caixinha"].read()
    if usar_veiculo and "veiculo" in request.files:
        veiculo_bytes = request.files["veiculo"].read()

    try:
        produtos_sem_fundo = [remove_bg(b) for _, b in produtos_bytes]
        caixinha_sem_fundo = remove_bg(caixinha_bytes) if caixinha_bytes else None
        veiculo_sem_fundo  = remove_bg(veiculo_bytes)  if veiculo_bytes  else None

        indices_colagem = set()
        if usar_caixinha and caixinha_sem_fundo and 0 <= idx_caixinha < len(produtos_sem_fundo):
            indices_colagem.add(idx_caixinha)
        if usar_veiculo and veiculo_sem_fundo and 0 <= idx_veiculo < len(produtos_sem_fundo):
            indices_colagem.add(idx_veiculo)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

            # ── Produtos individuais ──
            for i, (nome_original, _) in enumerate(produtos_bytes):
                if i in indices_colagem:
                    continue
                prod_img = Image.open(io.BytesIO(produtos_sem_fundo[i])).convert("RGBA")
                if fundo_branco:
                    prod_img = to_white_bg(produtos_sem_fundo[i])
                canvas_img = make_canvas_produto(prod_img, escala_produto=escala_produto)
                buf = io.BytesIO()
                canvas_img.save(buf, format="PNG")
                zf.writestr(os.path.splitext(nome_original)[0] + ".png", buf.getvalue())

            # ── Colagem caixinha ──
            if usar_caixinha and caixinha_sem_fundo and 0 <= idx_caixinha < len(produtos_sem_fundo):
                prod_img  = Image.open(io.BytesIO(produtos_sem_fundo[idx_caixinha])).convert("RGBA")
                caixa_img = Image.open(io.BytesIO(caixinha_sem_fundo)).convert("RGBA")
                if fundo_branco:
                    prod_img = to_white_bg(produtos_sem_fundo[idx_caixinha])
                canvas_img = make_canvas_com_elemento(
                    prod_img, caixa_img,
                    escala_produto=escala_produto,
                    escala_elemento=escala_caixinha,
                    pos_x=pos_box_x,
                    pos_y=pos_box_y
                )
                buf = io.BytesIO()
                canvas_img.save(buf, format="PNG")
                nome_base = os.path.splitext(produtos_bytes[idx_caixinha][0])[0]
                zf.writestr(f"{nome_base}_com_caixinha.png", buf.getvalue())

            # ── Colagem veículo ──
            if usar_veiculo and veiculo_sem_fundo and 0 <= idx_veiculo < len(produtos_sem_fundo):
                prod_img    = Image.open(io.BytesIO(produtos_sem_fundo[idx_veiculo])).convert("RGBA")
                veiculo_img = Image.open(io.BytesIO(veiculo_sem_fundo)).convert("RGBA")
                if fundo_branco:
                    prod_img = to_white_bg(produtos_sem_fundo[idx_veiculo])
                canvas_img = make_canvas_com_elemento(
                    prod_img, veiculo_img,
                    escala_produto=escala_produto,
                    escala_elemento=escala_veiculo,
                    pos_x=pos_vehicle_x,
                    pos_y=pos_vehicle_y
                )
                buf = io.BytesIO()
                canvas_img.save(buf, format="PNG")
                nome_base = os.path.splitext(produtos_bytes[idx_veiculo][0])[0]
                zf.writestr(f"{nome_base}_com_veiculo.png", buf.getvalue())

        zip_buffer.seek(0)
        return send_file(zip_buffer, mimetype="application/zip",
                         download_name="imagens_processadas.zip")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=False, host="0.0.0.0", port=port)
