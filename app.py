from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from PIL import Image
import requests
import io
import os
import zipfile

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

REMOVE_BG_API_KEY = "ZJd4zUtMWr8eytgp17MRBjTk"
OUTPUT_SIZE = (1800, 1800)


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


def make_canvas(product_no_bg_bytes, fundo_branco,
                box_no_bg_bytes=None, vehicle_no_bg_bytes=None):
    W, H = OUTPUT_SIZE
    canvas = Image.new("RGBA", OUTPUT_SIZE, (255, 255, 255, 255))

    # Produto centralizado — 92% do canvas
    prod_img = Image.open(io.BytesIO(product_no_bg_bytes)).convert("RGBA")
    prod_max = int(W * 0.92)
    prod_img.thumbnail((prod_max, prod_max), Image.LANCZOS)
    px = (W - prod_img.width) // 2
    py = (H - prod_img.height) // 2
    canvas.paste(prod_img, (px, py), prod_img)

    # Caixinha — canto inferior direito (35% do canvas)
    if box_no_bg_bytes:
        box_img = Image.open(io.BytesIO(box_no_bg_bytes)).convert("RGBA")
        box_max = int(W * 0.35)
        box_img.thumbnail((box_max, box_max), Image.LANCZOS)
        margin = 30
        bx = W - box_img.width - margin
        by = H - box_img.height - margin
        canvas.paste(box_img, (bx, by), box_img)

    # Veículo — canto superior direito (42% largura, 38% altura)
    if vehicle_no_bg_bytes:
        veh_img = Image.open(io.BytesIO(vehicle_no_bg_bytes)).convert("RGBA")
        veh_img.thumbnail((int(W * 0.42), int(H * 0.38)), Image.LANCZOS)
        margin = 30
        vx = W - veh_img.width - margin
        vy = margin
        canvas.paste(veh_img, (vx, vy), veh_img)

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
        # Lê tudo em memória
        product_bytes_list = [f.read() for f in product_files]
        products_no_bg = [remove_background(pb) for pb in product_bytes_list]

        box_no_bg = remove_background(box_file.read()) if box_file and box_product_index != "" else None
        vehicle_no_bg = remove_background(vehicle_file.read()) if vehicle_file and vehicle_product_index != "" else None

        box_idx = int(box_product_index) if box_product_index != "" else None
        vehicle_idx = int(vehicle_product_index) if vehicle_product_index != "" else None

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:

            # Produtos individuais — sem caixinha/veículo
            for i, no_bg in enumerate(products_no_bg):
                result = make_canvas(no_bg, fundo_branco)
                zf.writestr(f"produto_{i+1}.png", result)

            # Uma única colagem com caixinha
            if box_idx is not None and box_no_bg is not None:
                result = make_canvas(products_no_bg[box_idx], fundo_branco, box_no_bg, None)
                zf.writestr("colagem_caixinha.png", result)

            # Uma única colagem com veículo
            if vehicle_idx is not None and vehicle_no_bg is not None:
                result = make_canvas(products_no_bg[vehicle_idx], fundo_branco, None, vehicle_no_bg)
                zf.writestr("colagem_veiculo.png", result)

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
