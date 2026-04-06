#!/usr/bin/env python3
"""
Migra dados do data.json para o Firebase Firestore.
Uso: python migrate_to_firebase.py
"""
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore

FIREBASE_CRED = os.environ.get('FIREBASE_CREDENTIALS', 'firebase-credentials.json')

if not os.path.exists(FIREBASE_CRED):
    print(f"Arquivo de credenciais '{FIREBASE_CRED}' nao encontrado.")
    print("Coloque o arquivo JSON de servico do Firebase na pasta do projeto.")
    exit(1)

if not os.path.exists('data.json'):
    print("Arquivo data.json nao encontrado.")
    exit(1)

# Initialize Firebase
cred = credentials.Certificate(FIREBASE_CRED)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Load JSON data
with open('data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Migrate products
products = data.get('products', [])
print(f"\nMigrando {len(products)} produtos...")
for p in products:
    doc_id = p.get('id', '')
    doc_data = {k: v for k, v in p.items() if k != 'id'}
    db.collection('products').document(doc_id).set(doc_data)
    print(f"  [OK] {p.get('name', doc_id)}")

# Migrate announcements
announcements = data.get('announcements', [])
print(f"\nMigrando {len(announcements)} anuncios...")
for a in announcements:
    doc_id = a.get('id', '')
    doc_data = {k: v for k, v in a.items() if k != 'id'}
    db.collection('announcements').document(doc_id).set(doc_data)
    print(f"  [OK] {a.get('title', doc_id)}")

# Migrate customers (if any)
customers = data.get('customers', [])
if customers:
    print(f"\nMigrando {len(customers)} clientes...")
    for c in customers:
        doc_id = c.get('id', '')
        doc_data = {k: v for k, v in c.items() if k != 'id'}
        db.collection('customers').document(doc_id).set(doc_data)
        print(f"  [OK] {c.get('name', doc_id)}")

# Migrate orders (if any)
orders = data.get('orders', [])
if orders:
    print(f"\nMigrando {len(orders)} pedidos...")
    for o in orders:
        doc_id = o.get('id', '')
        doc_data = {k: v for k, v in o.items() if k != 'id'}
        db.collection('orders').document(doc_id).set(doc_data)
        print(f"  [OK] {o.get('order_number', doc_id)}")

print(f"\nMigracao concluida!")
print(f"  Produtos: {len(products)}")
print(f"  Anuncios: {len(announcements)}")
print(f"  Clientes: {len(customers)}")
print(f"  Pedidos: {len(orders)}")
print(f"\nAgora o app usara Firebase Firestore automaticamente.")
