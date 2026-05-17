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
    response = requests.post(
        "https://api.remove.bg/v1.0/removebg",
        files={"image_file": ("image.png", image_bytes)},
        data={"size": "auto"},
        headers={"X-Api-Key": REMOVE_BG_API_KEY},
    )
    if response.status_code != 200:
        raise Exception("Erro na API remove.bg: " + response.text)
    return response.content


def fit_into_canvas(img_bytes, fundo_branco):
    """Coloca imagem PNG em canvas 1800x1800 com padding"""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    img.thumbnail((OUTPUT_SIZE[0] - 80, OUTPUT_SIZE[1] - 80), Image.LANCZOS)

    if fundo_branco:
        canvas = Image.new("RGB", OUTPUT_SIZE, (255, 255, 255))
        # Cria versão RGB da imagem colando sobre branco
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img_rgb = bg.convert("RGB")
        x = (OUTPUT_SIZE[0] - img_rgb.width) // 2
        y = (OUTPUT_SIZE[1] - img_rgb.height) // 2
        canvas.paste(img_rgb, (x, y))
    else:
        canvas = Image.new("RGBA", OUTPUT_SIZE, (0, 0, 0, 0))
        x = (OUTPUT_SIZE[0] - img.width) // 2
        y = (OUTPUT_SIZE[1] - img.height) // 2
        canvas.paste(img, (x, y), img)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def create_collage(product_no_bg_bytes, extra_no_bg_bytes, fundo_branco):
    """Cria colagem lado a lado: [Produto | Extra] em 1800x1800"""
    canvas = Image.new("RGBA", OUTPUT_SIZE, (255, 255, 255, 255))
    half_w = OUTPUT_SIZE[0] // 2
    full_h = OUTPUT_SIZE[1]

    # Produto (esquerda)
    prod_img = Image.open(io.BytesIO(product_no_bg_bytes)).convert("RGBA")
    prod_img.thumbnail((half_w - 60, full_h - 60), Image.LANCZOS)
    px = (half_w - prod_img.width) // 2
    py = (full_h - prod_img.height) // 2
    canvas.paste(prod_img, (px, py), prod_img)

    # Extra (direita)
    extra_img = Image.open(io.BytesIO(extra_no_bg_bytes)).convert("RGBA")
    extra_img.thumbnail((half_w - 60, full_h - 60), Image.LANCZOS)
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


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/process", methods=["POST"])
def process():
    fundo_branco = request.form.get("fundo_branco", "false").lower() == "true"
    box_product_index = request.form.get("box_product_index", "")
    vehicle_product_index = request.form.get("vehicle_product_index", "")

    product_files = request.files.getlist("images[]")
    box_file = request.files.get("box_image")
    vehicle_file = request.files.get("vehicle_image")

    if not product_files:
        return jsonify({"error": "Nenhuma imagem de produto enviada."}), 400

    try:
        # Lê todos os produtos em memória primeiro
        product_bytes_list = [f.read() for f in product_files]

        # Remove fundo de todos os produtos
        products_no_bg = []
        for pb in product_bytes_list:
            no_bg = remove_background(pb)
            products_no_bg.append(no_bg)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

            # Produtos individuais
            for i, no_bg in enumerate(products_no_bg):
                result = fit_into_canvas(no_bg, fundo_branco)
                zf.writestr(f"produto_{i+1}.png", result)

            # Colagem com caixinha
            if box_file and box_product_index != "":
                idx = int(box_product_index)
                box_bytes = box_file.read()
                box_no_bg = remove_background(box_bytes)
                collage = create_collage(products_no_bg[idx], box_no_bg, fundo_branco)
                zf.writestr("colagem_caixinha.png", collage)

            # Colagem com veículo
            if vehicle_file and vehicle_product_index != "":
                idx = int(vehicle_product_index)
                vehicle_bytes = vehicle_file.read()
                vehicle_no_bg = remove_background(vehicle_bytes)
                collage = create_collage(products_no_bg[idx], vehicle_no_bg, fundo_branco)
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
    port = int(os.environ.get("PORT", 10000))
    print("=" * 50)
    print("  Removedor de Fundo Pro — Iniciando...")
    print(f"  Acesse: http://localhost:{port}")
    print("=" * 50)
    app.run(debug=False, host="0.0.0.0", port=port)
