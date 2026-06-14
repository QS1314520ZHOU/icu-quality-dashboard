@echo off
echo ==================================================
echo         ICU Quality Dashboard - Startup Script
echo ==================================================

echo [1/3] Checking and installing Python backend dependencies...
cd icu-quality-backend
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] pip install failed, trying Tsinghua mirror source...
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
cd ..

echo [2/3] Checking and installing Vue frontend dependencies...
cd icu-quality-dashboard
call npm install
cd ..

echo [3/3] Starting frontend and backend services in parallel...
echo Backend server will run at http://localhost:8000
echo Frontend dev server will run at http://localhost:5173
echo.

:: Start Backend
start "FastAPI Backend" cmd /k "cd icu-quality-backend && python -m uvicorn main:app --port 8000 --reload"

:: Start Frontend
start "Vite Frontend" cmd /k "cd icu-quality-dashboard && npm run dev"

echo Startup commands executed successfully. Please check the new command windows!
echo If everything is fine, visit: http://localhost:5173
echo.
pause
