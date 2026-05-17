from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from rembg import remove, new_session
from PIL import Image
import io
import os

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

# Carrega o modelo leve uma única vez ao iniciar o servidor
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
        return jsonify({"error": "Formato não suportado. Use PNG, JPG, JPEG, WEBP ou BMP."}), 400

    # Verifica se o usuário quer fundo branco ou transparente
    fundo_branco = request.form.get("fundo_branco", "false").lower() == "true"

    try:
        input_bytes = file.read()

        # 1. Abre a imagem
        image = Image.open(io.BytesIO(input_bytes))

        # 2. Redimensiona se for muito grande (mantém proporção)
        max_size = 1024
        if max(image.size) > max_size:
            image.thumbnail((max_size, max_size), Image.LANCZOS)

        # 3. Converte de volta para bytes
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        input_bytes = buffer.getvalue()

        # 4. Remove o fundo com o modelo leve u2netp
        output_bytes = remove(input_bytes, session=session)

        # 5. Se o usuário quiser fundo branco, aplica
        if fundo_branco:
            imagem_sem_fundo = Image.open(io.BytesIO(output_bytes)).convert("RGBA")

            # Cria uma tela branca do mesmo tamanho
            fundo = Image.new("RGBA", imagem_sem_fundo.size, (255, 255, 255, 255))

            # Cola a imagem sem fundo sobre o fundo branco
            fundo.paste(imagem_sem_fundo, mask=imagem_sem_fundo.split()[3])

            # Converte para RGB e salva como PNG
            resultado = fundo.convert("RGB")
            buffer_final = io.BytesIO()
            resultado.save(buffer_final, format="PNG")
            output_bytes = buffer_final.getvalue()

        return send_file(
            io.BytesIO(output_bytes),
            mimetype="image/png",
            as_attachment=False,
            download_name="sem_fundo.png",
        )

    except Exception as e:
        return jsonify({"error": f"Erro ao processar a imagem: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print("  Removedor de Fundo — Iniciando servidor...")
    print(f"  Acesse: http://localhost:{port}")
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=port)
