from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from PIL import Image
import requests
import io
import os
import zipfile

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

REMOVE_BG_API_KEY = "BwrvNfpZ33qsVyp6heGBhxTs"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}
OUTPUT_SIZE = (1800, 1800)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def remove_background(image_bytes):
    """Remove o fundo de uma imagem usando a API do remove.bg"""
    response = requests.post(
        "https://api.remove.bg/v1.0/removebg",
        files={"image_file": ("image.png", image_bytes)},
        data={"size": "auto"},
        headers={"X-Api-Key": REMOVE_BG_API_KEY},
    )
    if response.status_code != 200:
        raise Exception("Erro na API remove.bg: " + response.text)
    return response.content


def apply_white_background(image_bytes):
    """Aplica fundo branco em uma imagem PNG transparente"""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    fundo = Image.new("RGBA", img.size, (255, 255, 255, 255))
    fundo.paste(img, mask=img.split()[3])
    result = fundo.convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


def fit_image_into(img, max_w, max_h):
    """Redimensiona mantendo proporção dentro de um box"""
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img


def create_collage(product_bytes, extra_bytes, fundo_branco):
    """
    Cria colagem lado a lado: [Produto | Extra]
    Produto e Extra já devem ter fundo removido.
    Tamanho final: 1800x1800
    """
    canvas = Image.new("RGBA", OUTPUT_SIZE, (255, 255, 255, 255))

    half_w = OUTPUT_SIZE[0] // 2  # 900px para cada lado
    full_h = OUTPUT_SIZE[1]        # 1800px de altura

    # Produto (lado esquerdo)
    product_img = Image.open(io.BytesIO(product_bytes)).convert("RGBA")
    product_img = fit_image_into(product_img, half_w - 40, full_h - 40)
    px = (half_w - product_img.width) // 2
    py = (full_h - product_img.height) // 2
    canvas.paste(product_img, (px, py), product_img)

    # Extra (caixinha ou veículo) (lado direito)
    extra_img = Image.open(io.BytesIO(extra_bytes)).convert("RGBA")
    extra_img = fit_image_into(extra_img, half_w - 40, full_h - 40)
    ex = half_w + (half_w - extra_img.width) // 2
    ey = (full_h - extra_img.height) // 2
    canvas.paste(extra_img, (ex, ey), extra_img)

    if fundo_branco:
        result = canvas.convert("RGB")
    else:
        result = canvas

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


def process_single(image_bytes, fundo_branco):
    """Remove fundo e aplica fundo branco se necessário"""
    output = remove_background(image_bytes)
    if fundo_branco:
        output = apply_white_background(output)

    # Redimensiona para 1800x1800 mantendo proporção com padding
    img = Image.open(io.BytesIO(output)).convert("RGBA" if not fundo_branco else "RGB")
    canvas_mode = "RGB" if fundo_branco else "RGBA"
    canvas_bg = (255, 255, 255, 255) if not fundo_branco else (255, 255, 255)
    canvas = Image.new(canvas_mode, OUTPUT_SIZE, canvas_bg)
    img = fit_image_into(img, OUTPUT_SIZE[0] - 80, OUTPUT_SIZE[1] - 80)
    x = (OUTPUT_SIZE[0] - img.width) // 2
    y = (OUTPUT_SIZE[1] - img.height) // 2
    if canvas_mode == "RGBA":
        canvas.paste(img, (x, y), img)
    else:
        canvas.paste(img, (x, y))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/process", methods=["POST"])
def process():
    """
    Processa todas as imagens e retorna um ZIP com os resultados.
    Campos do formulário:
    - images[]: lista de imagens de produtos
    - box_image: imagem da caixinha (opcional)
    - vehicle_image: imagem do veículo (opcional)
    - fundo_branco: "true" ou "false"
    - box_product_index: índice do produto para colagem com caixinha
    - vehicle_product_index: índice do produto para colagem com veículo
    """
    fundo_branco = request.form.get("fundo_branco", "false").lower() == "true"
    box_product_index = request.form.get("box_product_index", None)
    vehicle_product_index = request.form.get("vehicle_product_index", None)

    product_files = request.files.getlist("images[]")
    box_file = request.files.get("box_image")
    vehicle_file = request.files.get("vehicle_image")

    if not product_files:
        return jsonify({"error": "Nenhuma imagem de produto enviada."}), 400

    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

            # 1. Processa cada produto individualmente
            processed_products = []
            for i, f in enumerate(product_files):
                img_bytes = f.read()
                result = process_single(img_bytes, fundo_branco)
                processed_products.append(result)
                zf.writestr(f"produto_{i+1}.png", result)

            # 2. Colagem com caixinha
            if box_file and box_product_index is not None:
                idx = int(box_product_index)
                box_bytes = box_file.read()
                box_no_bg = remove_background(box_bytes)

                product_no_bg = remove_background(product_files[idx].stream.read() if hasattr(product_files[idx], 'stream') else b"")

                # Usa o produto já processado (sem fundo, sem fundo branco forçado para colagem)
                product_raw = Image.open(io.BytesIO(processed_products[idx])).convert("RGBA")
                product_buf = io.BytesIO()
                product_raw.save(product_buf, format="PNG")

                collage = create_collage(product_buf.getvalue(), box_no_bg, fundo_branco)
                zf.writestr("colagem_caixinha.png", collage)

            # 3. Colagem com veículo
            if vehicle_file and vehicle_product_index is not None:
                idx = int(vehicle_product_index)
                vehicle_bytes = vehicle_file.read()
                vehicle_no_bg = remove_background(vehicle_bytes)

                product_raw = Image.open(io.BytesIO(processed_products[idx])).convert("RGBA")
                product_buf = io.BytesIO()
                product_raw.save(product_buf, format="PNG")

                collage = create_collage(product_buf.getvalue(), vehicle_no_bg, fundo_branco)
                zf.writestr("colagem_veiculo.png", collage)

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name="imagens_processadas.zip",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print("  Removedor de Fundo Pro — Iniciando...")
    print(f"  Acesse: http://localhost:{port}")
    print("=" * 50)
    app.run(debug=False, host="0.0.0.0", port=port)
