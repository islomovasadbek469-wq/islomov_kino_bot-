@echo off
title Islomov Kino Bot
chcp 65001 > nul
echo ==============================================
echo        Islomov Kino Telegram Boti
echo ==============================================
echo.

if not exist ".env" (
    echo [OGOHLANTIRISH] .env fayli topilmadi! .env.example dan nusxa olinmoqda...
    copy .env.example .env
    echo Iltimos, .env fayliga bot tokeni va admin ID sini kiriting!
    pause
    exit /b
)

echo Bot ishga tushirilmoqda...
python main.py

pause
