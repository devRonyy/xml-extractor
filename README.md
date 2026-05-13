
# XML Flatten ZIP Extractor

## Instalación

1. Instalar Python 3.11 o superior

2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Ejecutar servidor:

```bash
uvicorn app:app --reload
```

4. Abrir navegador:

http://127.0.0.1:8000

---

## Funcionalidades

- Extrae XMLs de cualquier ZIP
- Funciona recursivamente
- Evita duplicados
- Genera ZIP plano
- Protegido contra ZIP Slip

---

## Compartir con otros

### Opción 1
Compartir la carpeta del proyecto.

### Opción 2
Crear EXE con PyInstaller:

```bash
pip install pyinstaller
pyinstaller --onefile app.py
```
