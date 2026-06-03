from flask import Flask, request, send_file, jsonify
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
    """Remove o fundo de uma imagem e retorna bytes RGBA."""
    image = Image.open(io.BytesIO(image_bytes))
    if max(image.size) > 1200:
        image.thumbnail((1200, 1200), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return remove(buf.getvalue(), session=session)

def to_white_bg(rgba_bytes):
    """Coloca fundo branco em uma imagem RGBA."""
    img = Image.open(io.BytesIO(rgba_bytes)).convert("RGBA")
    fundo = Image.new("RGBA", img.size, (255, 255, 255, 255))
    fundo.paste(img, mask=img.split()[3])
    return fundo.convert("RGB")

def resize_contain(img, max_w, max_h):
    """Redimensiona mantendo proporção dentro de max_w x max_h."""
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img

def make_canvas(produto_img, extra_img=None, posicao_extra=None):
    """
    Monta canvas 1800x1800.
    produto_img: PIL Image (RGB ou RGBA)
    extra_img: PIL Image opcional (caixinha ou veículo)
    posicao_extra: 'inferior_direito' ou 'superior_direito'
    """
    canvas_size = 1800
    canvas = Image.new("RGB", (canvas_size, canvas_size), (255, 255, 255))

    if extra_img is None:
        # Produto centralizado ocupando 90% do canvas
        produto = resize_contain(produto_img.copy(), int(canvas_size * 0.90), int(canvas_size * 0.90))
        px = (canvas_size - produto.width) // 2
        py = (canvas_size - produto.height) // 2
        if produto.mode == "RGBA":
            canvas.paste(produto, (px, py), produto.split()[3])
        else:
            canvas.paste(produto, (px, py))
    else:
        # Produto ocupa 70% do canvas, centralizado
        produto = resize_contain(produto_img.copy(), int(canvas_size * 0.70), int(canvas_size * 0.70))
        px = (canvas_size - produto.width) // 2
        py = (canvas_size - produto.height) // 2
        if produto.mode == "RGBA":
            canvas.paste(produto, (px, py), produto.split()[3])
        else:
            canvas.paste(produto, (px, py))

        # Extra ocupa 35% do canvas
        extra = resize_contain(extra_img.copy(), int(canvas_size * 0.35), int(canvas_size * 0.35))
        margin = 40
        if posicao_extra == "inferior_direito":
            ex = canvas_size - extra.width - margin
            ey = canvas_size - extra.height - margin
        else:  # superior_direito
            ex = canvas_size - extra.width - margin
            ey = margin

        if extra.mode == "RGBA":
            canvas.paste(extra, (ex, ey), extra.split()[3])
        else:
            canvas.paste(extra, (ex, ey))

    return canvas

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/remove-bg", methods=["POST"])
def remove_background():
    # Pega opções
    fundo_branco = request.form.get("fundo_branco", "false").lower() == "true"
    usar_caixinha = request.form.get("usar_caixinha", "false").lower() == "true"
    usar_veiculo = request.form.get("usar_veiculo", "false").lower() == "true"
    idx_caixinha = request.form.get("idx_caixinha", "-1")
    idx_veiculo = request.form.get("idx_veiculo", "-1")

    try:
        idx_caixinha = int(idx_caixinha)
        idx_veiculo = int(idx_veiculo)
    except ValueError:
        idx_caixinha = -1
        idx_veiculo = -1

    # Pega produtos
    produtos_files = request.files.getlist("produtos")
    if not produtos_files:
        return jsonify({"error": "Nenhuma imagem enviada."}), 400

    # Lê todos os bytes dos produtos
    produtos_bytes = []
    for f in produtos_files:
        if not allowed_file(f.filename):
            return jsonify({"error": f"Formato não suportado: {f.filename}"}), 400
        produtos_bytes.append(f.read())

    # Pega caixinha e veículo se existirem
    caixinha_bytes = None
    veiculo_bytes = None
    if usar_caixinha and "caixinha" in request.files:
        caixinha_bytes = request.files["caixinha"].read()
    if usar_veiculo and "veiculo" in request.files:
        veiculo_bytes = request.files["veiculo"].read()

    try:
        # Remove fundo de todos os produtos
        produtos_sem_fundo = [remove_bg(b) for b in produtos_bytes]

        # Remove fundo da caixinha e veículo se houver
        caixinha_sem_fundo = remove_bg(caixinha_bytes) if caixinha_bytes else None
        veiculo_sem_fundo = remove_bg(veiculo_bytes) if veiculo_bytes else None

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Produtos individuais
            for i, prod_bytes in enumerate(produtos_sem_fundo):
                prod_img = Image.open(io.BytesIO(prod_bytes)).convert("RGBA")

                if fundo_branco:
                    canvas = make_canvas(to_white_bg(prod_bytes))
                else:
                    canvas = make_canvas(prod_img)

                buf = io.BytesIO()
                canvas.save(buf, format="PNG")
                zf.writestr(f"produto_{i+1}.png", buf.getvalue())

            # Colagem com caixinha
            if usar_caixinha and caixinha_sem_fundo and 0 <= idx_caixinha < len(produtos_sem_fundo):
                prod_bytes = produtos_sem_fundo[idx_caixinha]
                prod_img = Image.open(io.BytesIO(prod_bytes)).convert("RGBA")
                caixa_img = Image.open(io.BytesIO(caixinha_sem_fundo)).convert("RGBA")

                if fundo_branco:
                    prod_final = to_white_bg(prod_bytes)
                else:
                    prod_final = prod_img

                canvas = make_canvas(prod_final, caixa_img, "inferior_direito")
                buf = io.BytesIO()
                canvas.save(buf, format="PNG")
                zf.writestr("colagem_caixinha.png", buf.getvalue())

            # Colagem com veículo
            if usar_veiculo and veiculo_sem_fundo and 0 <= idx_veiculo < len(produtos_sem_fundo):
                prod_bytes = produtos_sem_fundo[idx_veiculo]
                prod_img = Image.open(io.BytesIO(prod_bytes)).convert("RGBA")
                veiculo_img = Image.open(io.BytesIO(veiculo_sem_fundo)).convert("RGBA")

                if fundo_branco:
                    prod_final = to_white_bg(prod_bytes)
                else:
                    prod_final = prod_img

                canvas = make_canvas(prod_final, veiculo_img, "superior_direito")
                buf = io.BytesIO()
                canvas.save(buf, format="PNG")
                zf.writestr("colagem_veiculo.png", buf.getvalue())

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            download_name="imagens_processadas.zip",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(debug=False, host="0.0.0.0", port=port)
