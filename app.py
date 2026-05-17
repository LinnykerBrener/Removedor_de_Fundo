from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from rembg import remove, new_session
from PIL import Image
import io
import os
os.environ["ONNXRUNTIME_PROVIDERS"] = "CPUExecutionProvider"

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

print("Carregando modelo de IA... aguarde.")
session = new_session("u2netp")
print("Modelo carregado! Servidor pronto.")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/remove-bg", methods=["POST"])
def remove_background():
    if "image" not in request.files:
        return jsonify({"error": "Nenhuma imagem enviada."}), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({"error": "Arquivo sem nome."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Formato não suportado."}), 400

    fundo_branco = request.form.get("fundo_branco", "false").lower() == "true"

    try:
        input_bytes = file.read()

        image = Image.open(io.BytesIO(input_bytes))
        if max(image.size) > 1024:
            image.thumbnail((1024, 1024), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            input_bytes = buffer.getvalue()

        output_bytes = remove(input_bytes, session=session)

        if fundo_branco:
            imagem_sem_fundo = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
            fundo = Image.new("RGBA", imagem_sem_fundo.size, (255, 255, 255, 255))
            fundo.paste(imagem_sem_fundo, mask=imagem_sem_fundo.split()[3])
            resultado = fundo.convert("RGB")
            buffer_final = io.BytesIO()
            resultado.save(buffer_final, format="PNG")
            output_bytes = buffer_final.getvalue()

        return send_file(
            io.BytesIO(output_bytes),
            mimetype="image/png",
            download_name="sem_fundo.png",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
