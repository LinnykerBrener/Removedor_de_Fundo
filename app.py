rom flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from rembg import remove, new_session
from PIL import Image
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
 
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
 
def remove_bg(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    if max(image.size) > 1200:
        image.thumbnail((1200, 1200), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return remove(buf.getvalue(), session=session)
 
def to_white_bg(rgba_bytes):
    img = Image.open(io.BytesIO(rgba_bytes)).convert("RGBA")
    fundo = Image.new("RGBA", img.size, (255, 255, 255, 255))
    fundo.paste(img, mask=img.split()[3])
    return fundo.convert("RGBA")
 
def resize_to_scale(img, canvas_size, escala):
    """Redimensiona a imagem para ocupar 'escala' do canvas, mantendo proporção."""
    img = img.copy()
    max_dim = int(canvas_size * escala)
    w, h = img.size
    if w == 0 or h == 0:
        return img
    ratio = min(max_dim / w, max_dim / h)
    new_w = int(w * ratio)
    new_h = int(h * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)
 
def paste_rgba(canvas, img, x, y):
    if img.mode == "RGBA":
        canvas.paste(img, (x, y), img.split()[3])
    else:
        canvas.paste(img, (x, y))
 
def make_canvas(produto_img, extra_img=None, posicao_extra=None,
                escala_produto=0.90, escala_extra=0.40,
                offset_x=0, offset_y=0):
    """
    Monta canvas 1800×1800.
    offset_x / offset_y: valor de -100 a 100, onde ±100 equivale a ±20% do canvas (360px).
    Positivo X → move para a direita; Positivo Y → move para baixo.
    """
    CANVAS = 1800
    MARGIN = 40
 
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 255))
 
    # Produto centrado
    produto = resize_to_scale(produto_img.convert("RGBA"), CANVAS, escala_produto)
    px = (CANVAS - produto.width) // 2
    py = (CANVAS - produto.height) // 2
    paste_rgba(canvas, produto, px, py)
 
    # Extra (caixinha ou veículo) com offset
    if extra_img is not None:
        extra = resize_to_scale(extra_img.convert("RGBA"), CANVAS, escala_extra)
 
        # Deslocamento: offset ±100 → ±20% do canvas = ±360px
        delta_x = int((offset_x / 100.0) * CANVAS * 0.20)
        delta_y = int((offset_y / 100.0) * CANVAS * 0.20)
 
        if posicao_extra == "inferior_direito":
            ex = CANVAS - extra.width - MARGIN + delta_x
            ey = CANVAS - extra.height - MARGIN + delta_y
        else:  # superior_direito
            ex = CANVAS - extra.width - MARGIN + delta_x
            ey = MARGIN + delta_y
 
        paste_rgba(canvas, extra, ex, ey)
 
    # Achata para RGB com fundo branco
    fundo = Image.new("RGB", (CANVAS, CANVAS), (255, 255, 255))
    fundo.paste(canvas, mask=canvas.split()[3])
    return fundo
 
 
@app.route("/")
def index():
    return app.send_static_file("index.html")
 
 
@app.route("/remove-bg", methods=["POST"])
def remove_background():
    fundo_branco  = request.form.get("fundo_branco",  "false").lower() == "true"
    usar_caixinha = request.form.get("usar_caixinha", "false").lower() == "true"
    usar_veiculo  = request.form.get("usar_veiculo",  "false").lower() == "true"
 
    try:
        idx_caixinha = int(request.form.get("idx_caixinha", "-1"))
    except ValueError:
        idx_caixinha = -1
    try:
        idx_veiculo = int(request.form.get("idx_veiculo", "-1"))
    except ValueError:
        idx_veiculo = -1
 
    # Escala do produto (30–150 → 0.30–1.50)
    try:
        escala_produto = float(request.form.get("escala_produto", "90")) / 100.0
        escala_produto = max(0.30, min(1.50, escala_produto))
    except ValueError:
        escala_produto = 0.90
 
    # Escala da caixinha (separada)
    try:
        escala_caixinha = float(request.form.get("escala_caixinha", "40")) / 100.0
        escala_caixinha = max(0.30, min(1.50, escala_caixinha))
    except ValueError:
        escala_caixinha = 0.40
 
    # Escala do veículo (separada)
    try:
        escala_veiculo = float(request.form.get("escala_veiculo", "40")) / 100.0
        escala_veiculo = max(0.30, min(1.50, escala_veiculo))
    except ValueError:
        escala_veiculo = 0.40
 
    # Offsets de posição (-100 a 100)
    try:
        offset_box_x = max(-100, min(100, int(request.form.get("offset_box_x", "0"))))
    except ValueError:
        offset_box_x = 0
    try:
        offset_box_y = max(-100, min(100, int(request.form.get("offset_box_y", "0"))))
    except ValueError:
        offset_box_y = 0
    try:
        offset_vehicle_x = max(-100, min(100, int(request.form.get("offset_vehicle_x", "0"))))
    except ValueError:
        offset_vehicle_x = 0
    try:
        offset_vehicle_y = max(-100, min(100, int(request.form.get("offset_vehicle_y", "0"))))
    except ValueError:
        offset_vehicle_y = 0
 
    print(f"[DEBUG] escala_produto={escala_produto:.2f} "
          f"escala_caixinha={escala_caixinha:.2f} escala_veiculo={escala_veiculo:.2f} "
          f"offset_box=({offset_box_x},{offset_box_y}) "
          f"offset_vehicle=({offset_vehicle_x},{offset_vehicle_y})")
 
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
 
            # Produtos individuais
            for i, (nome_original, _) in enumerate(produtos_bytes):
                if i in indices_colagem:
                    continue
                prod_rgba = Image.open(io.BytesIO(produtos_sem_fundo[i])).convert("RGBA")
                if fundo_branco:
                    prod_entrada = to_white_bg(produtos_sem_fundo[i])
                else:
                    prod_entrada = prod_rgba
                canvas = make_canvas(prod_entrada, escala_produto=escala_produto)
                buf = io.BytesIO()
                canvas.save(buf, format="PNG")
                zf.writestr(os.path.splitext(nome_original)[0] + ".png", buf.getvalue())
 
            # Colagem caixinha
            if usar_caixinha and caixinha_sem_fundo and 0 <= idx_caixinha < len(produtos_sem_fundo):
                prod_rgba = Image.open(io.BytesIO(produtos_sem_fundo[idx_caixinha])).convert("RGBA")
                caixa_img = Image.open(io.BytesIO(caixinha_sem_fundo)).convert("RGBA")
                prod_entrada = to_white_bg(produtos_sem_fundo[idx_caixinha]) if fundo_branco else prod_rgba
                canvas = make_canvas(
                    prod_entrada, caixa_img, "inferior_direito",
                    escala_produto=escala_produto,
                    escala_extra=escala_caixinha,
                    offset_x=offset_box_x,
                    offset_y=offset_box_y
                )
                buf = io.BytesIO()
                canvas.save(buf, format="PNG")
                nome_base = os.path.splitext(produtos_bytes[idx_caixinha][0])[0]
                zf.writestr(f"{nome_base}_com_caixinha.png", buf.getvalue())
 
            # Colagem veículo
            if usar_veiculo and veiculo_sem_fundo and 0 <= idx_veiculo < len(produtos_sem_fundo):
                prod_rgba   = Image.open(io.BytesIO(produtos_sem_fundo[idx_veiculo])).convert("RGBA")
                veiculo_img = Image.open(io.BytesIO(veiculo_sem_fundo)).convert("RGBA")
                prod_entrada = to_white_bg(produtos_sem_fundo[idx_veiculo]) if fundo_branco else prod_rgba
                canvas = make_canvas(
                    prod_entrada, veiculo_img, "superior_direito",
                    escala_produto=escala_produto,
                    escala_extra=escala_veiculo,
                    offset_x=offset_vehicle_x,
                    offset_y=offset_vehicle_y
                )
                buf = io.BytesIO()
                canvas.save(buf, format="PNG")
                nome_base = os.path.splitext(produtos_bytes[idx_veiculo][0])[0]
                zf.writestr(f"{nome_base}_com_veiculo.png", buf.getvalue())
 
        zip_buffer.seek(0)
        return send_file(zip_buffer, mimetype="application/zip",
                         download_name="imagens_processadas.zip")
 
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=False, host="0.0.0.0", port=port)
