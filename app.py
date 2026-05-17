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
OUTPUT_SIZE = (1800, 1800)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}


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


def place_centered(canvas, img, max_w, max_h, offset_x=0, offset_y=0):
    """Coloca imagem centralizada no canvas dentro de um box"""
    img = img.copy()
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    x = offset_x + (max_w - img.width) // 2
    y = offset_y + (max_h - img.height) // 2
    canvas.paste(img, (x, y), img)
    return canvas


def make_product_canvas(product_no_bg_bytes, fundo_branco,
                         box_no_bg_bytes=None, vehicle_no_bg_bytes=None):
    """
    Monta canvas 1800x1800:
    - Produto centralizado ocupando ~80% do canvas
    - Caixinha no canto inferior direito (~30% do canvas)
    - Veículo no canto superior direito (~35% do canvas)
    """
    W, H = OUTPUT_SIZE

    # Canvas base branco
    canvas = Image.new("RGBA", OUTPUT_SIZE, (255, 255, 255, 255))

    # --- Produto centralizado e grande ---
    prod_img = Image.open(io.BytesIO(product_no_bg_bytes)).convert("RGBA")
    prod_max = int(W * 0.82)  # 82% do canvas
    prod_img.thumbnail((prod_max, prod_max), Image.LANCZOS)
    px = (W - prod_img.width) // 2
    py = (H - prod_img.height) // 2
    canvas.paste(prod_img, (px, py), prod_img)

    # --- Caixinha: canto inferior direito ---
    if box_no_bg_bytes:
        box_img = Image.open(io.BytesIO(box_no_bg_bytes)).convert("RGBA")
        box_max = int(W * 0.32)  # 32% do canvas
        box_img.thumbnail((box_max, box_max), Image.LANCZOS)
        margin = 40
        bx = W - box_img.width - margin
        by = H - box_img.height - margin
        canvas.paste(box_img, (bx, by), box_img)

    # --- Veículo: canto superior direito ---
    if vehicle_no_bg_bytes:
        veh_img = Image.open(io.BytesIO(vehicle_no_bg_bytes)).convert("RGBA")
        veh_max_w = int(W * 0.40)  # 40% largura
        veh_max_h = int(H * 0.35)  # 35% altura
        veh_img.thumbnail((veh_max_w, veh_max_h), Image.LANCZOS)
        margin = 40
        vx = W - veh_img.width - margin
        vy = margin
        canvas.paste(veh_img, (vx, vy), veh_img)

    # Aplica fundo
    if fundo_branco:
        result = canvas.convert("RGB")
    else:
        # Fundo transparente — remove o branco do canvas
        canvas_transp = Image.new("RGBA", OUTPUT_SIZE, (0, 0, 0, 0))
        # Cola produto
        prod_img2 = Image.open(io.BytesIO(product_no_bg_bytes)).convert("RGBA")
        prod_img2.thumbnail((prod_max, prod_max), Image.LANCZOS)
        px2 = (W - prod_img2.width) // 2
        py2 = (H - prod_img2.height) // 2
        canvas_transp.paste(prod_img2, (px2, py2), prod_img2)

        if box_no_bg_bytes:
            box_img2 = Image.open(io.BytesIO(box_no_bg_bytes)).convert("RGBA")
            box_img2.thumbnail((int(W * 0.32), int(W * 0.32)), Image.LANCZOS)
            bx2 = W - box_img2.width - 40
            by2 = H - box_img2.height - 40
            canvas_transp.paste(box_img2, (bx2, by2), box_img2)

        if vehicle_no_bg_bytes:
            veh_img2 = Image.open(io.BytesIO(vehicle_no_bg_bytes)).convert("RGBA")
            veh_img2.thumbnail((int(W * 0.40), int(H * 0.35)), Image.LANCZOS)
            vx2 = W - veh_img2.width - 40
            vy2 = 40
            canvas_transp.paste(veh_img2, (vx2, vy2), veh_img2)

        result = canvas_transp

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
        # Lê todos em memória
        product_bytes_list = [f.read() for f in product_files]

        # Remove fundo de todos os produtos
        products_no_bg = [remove_background(pb) for pb in product_bytes_list]

        # Remove fundo da caixinha e veículo se existirem
        box_no_bg = remove_background(box_file.read()) if box_file and box_product_index != "" else None
        vehicle_no_bg = remove_background(vehicle_file.read()) if vehicle_file and vehicle_product_index != "" else None

        box_idx = int(box_product_index) if box_product_index != "" else None
        vehicle_idx = int(vehicle_product_index) if vehicle_product_index != "" else None

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, no_bg in enumerate(products_no_bg):

                # Define se esse produto leva caixinha e/ou veículo
                use_box = box_no_bg if box_idx == i else None
                use_vehicle = vehicle_no_bg if vehicle_idx == i else None

                result = make_product_canvas(no_bg, fundo_branco, use_box, use_vehicle)
                zf.writestr(f"produto_{i+1}.png", result)

            # Se o mesmo produto foi escolhido para ambos, gera versão com os dois
            if box_idx is not None and vehicle_idx is not None and box_idx == vehicle_idx:
                result = make_product_canvas(
                    products_no_bg[box_idx], fundo_branco, box_no_bg, vehicle_no_bg
                )
                zf.writestr(f"produto_{box_idx+1}_completo.png", result)

            # Se produtos diferentes foram escolhidos, gera cada um separado
            elif box_idx is not None and vehicle_idx is not None and box_idx != vehicle_idx:
                # Produto com caixinha
                result_box = make_product_canvas(products_no_bg[box_idx], fundo_branco, box_no_bg, None)
                zf.writestr(f"produto_{box_idx+1}_com_caixinha.png", result_box)
                # Produto com veículo
                result_veh = make_product_canvas(products_no_bg[vehicle_idx], fundo_branco, None, vehicle_no_bg)
                zf.writestr(f"produto_{vehicle_idx+1}_com_veiculo.png", result_veh)

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
