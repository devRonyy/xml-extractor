from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import zipfile
import tempfile
import shutil
from pathlib import Path
import uuid
import sys
import os

# Compatibilidad con PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Extractor de XML")

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

MAX_FILE_SIZE_MB = 200
ALLOWED_EXTENSION = ".zip"

app = FastAPI(title="Extractor de XML")

BASE_DIR = Path(__file__).resolve().parent

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

MAX_FILE_SIZE_MB = 200
ALLOWED_EXTENSION = ".zip"


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


@app.post("/upload")
async def upload_zip(
    rut: str = Form(...),
    file: UploadFile = File(...)
):

    # Limpiar RUT
    rut = ''.join(filter(str.isdigit, rut))

    if not rut:
        return JSONResponse(
            status_code=400,
            content={"error": "El RUT ingresado no es válido"}
        )

    # Validar extensión
    if not file.filename.lower().endswith(ALLOWED_EXTENSION):
        return JSONResponse(
            status_code=400,
            content={"error": "Solo se permiten archivos ZIP"}
        )

    with tempfile.TemporaryDirectory() as temp_dir:

        temp_path = Path(temp_dir)

        input_zip_path = temp_path / "input.zip"

        # Guardar ZIP subido
        with open(input_zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Validar tamaño
        size_mb = input_zip_path.stat().st_size / (1024 * 1024)

        if size_mb > MAX_FILE_SIZE_MB:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"El archivo supera el límite de {MAX_FILE_SIZE_MB} MB"
                }
            )

        extract_dir = temp_path / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        # Extraer ZIP de forma segura
        try:
            with zipfile.ZipFile(input_zip_path, 'r') as zip_ref:

                for member in zip_ref.infolist():

                    member_path = extract_dir / member.filename

                    # Protección ZIP Slip
                    if not str(member_path.resolve()).startswith(str(extract_dir.resolve())):
                        return JSONResponse(
                            status_code=400,
                            content={"error": "ZIP inválido o inseguro"}
                        )

                zip_ref.extractall(extract_dir)

        except zipfile.BadZipFile:
            return JSONResponse(
                status_code=400,
                content={"error": "El archivo ZIP está corrupto"}
            )

        # Buscar XMLs recursivamente
        xml_files = []

        for path in extract_dir.rglob('*'):
            if path.is_file() and path.suffix.lower() == '.xml':
                xml_files.append(path)

        if not xml_files:
            return JSONResponse(
                status_code=400,
                content={"error": "No se encontraron archivos XML"}
            )

        # Crear ZIP plano
        output_zip_name = f"xml_flat_{uuid.uuid4().hex}.zip"
        output_zip_path = temp_path / output_zip_name

        used_names = {}

        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as output_zip:

            for xml_file in xml_files:

                original_name = xml_file.name
                final_name = original_name

                # Manejo de nombres duplicados
                if final_name.lower() in used_names:

                    used_names[final_name.lower()] += 1

                    stem = xml_file.stem
                    suffix = xml_file.suffix

                    final_name = f"{stem}_{used_names[final_name.lower()]}{suffix}"

                else:
                    used_names[final_name.lower()] = 0

                output_zip.write(
                    xml_file,
                    arcname=final_name
                )

        # Carpeta de salida final
        final_output_dir = BASE_DIR / "generated"
        final_output_dir.mkdir(exist_ok=True)

        final_output_path = final_output_dir / output_zip_name

        shutil.copy(output_zip_path, final_output_path)

    # Descargar ZIP final
    return FileResponse(
        path=final_output_path,
        filename=f"CFE-{rut}.zip",
        media_type='application/zip'
    )


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }