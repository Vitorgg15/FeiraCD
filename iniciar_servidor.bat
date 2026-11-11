@echo off
chcp 65001 >nul
title Empresário por 5 Minutos - Servidor Local
echo ================================================
echo   EMPRESARIO POR 5 MINUTOS - REDE LOCAL
echo ================================================
echo.
set /p ADMIN_PASSWORD=Crie a senha dos administradores (minimo 8 caracteres):
if "%ADMIN_PASSWORD%"=="" goto senha
if "%ADMIN_PASSWORD:~7,1%"=="" goto senha
set FLASK_SECRET=
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Nao foi possivel instalar as dependencias.
  echo Verifique se o Python esta instalado e tente novamente.
  pause
  exit /b 1
)
echo.
echo Descobrindo o endereco IPv4 deste notebook...
ipconfig | findstr /i "IPv4"
echo.
echo Abra no notebook publico: http://127.0.0.1:5000
echo Nos demais notebooks, use o IPv4 acima com :5000 no final.
echo Ranking TV: /ranking
echo Administracao: /admin
echo Mantenha esta janela aberta durante a feira.
echo.
py app.py
pause
exit /b 0
:senha
echo A senha precisa ter pelo menos 8 caracteres.
pause
goto :eof
