#!/usr/bin/env python3
"""QuoteCraft - Turn messy client WhatsApp messages into professional quotations,
scope-of-work, and ready-to-send replies in seconds.

Runs 100% locally with open-weight models (Llama 3.2 via Ollama).
Zero cloud APIs, zero per-token cost, 100% client data privacy.
"""

import datetime
import json
import os
import re
import urllib.request
import uuid

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
TEXT_MODEL = os.environ.get("TEXT_MODEL", "llama3.2")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quotes.json")

app = Flask(__name__)

# Sample client messages for quick testing
PRESETS = {
    "bakery_web": {
        "title": "🧁 Boutique Bakery Website",
        "profession": "Freelance Web Developer",
        "currency": "INR",
        "rate_tier": "standard",
        "message": (
            "hi vikram! need a landing page for our boutique bakery in dehradun with menu, "
            "photo gallery, online order enquiry form connected to whatsapp, and google maps location. "
            "we have logo and photos ready. how much will this cost and can we get it before diwali? "
            "also need 3 revisions and basic seo."
        )
    },
    "wedding_photo": {
        "title": "📸 Wedding Photography & Highlight Reel",
        "profession": "Wedding & Event Photographer",
        "currency": "INR",
        "rate_tier": "standard",
        "message": (
            "Hello, we have a 2-day wedding event in Rishikesh on Nov 24-25 (Mehendi + Wedding day). "
            "Need candid photography, traditional video coverage, 1 teaser reel for Instagram within 48 hours, "
            "and complete edited album with 250 printed photos. What are your charges and advance terms?"
        )
    },
    "fitness_app": {
        "title": "📱 Fitness Coaching App MVP",
        "profession": "Full-Stack Mobile Developer",
        "currency": "USD",
        "rate_tier": "standard",
        "message": (
            "Hey! Looking for an MVP mobile app for my personal training clients. "
            "Needs user login, daily workout checklist with video demo links, workout logging, "
            "and Stripe payment for monthly coaching subscription. iOS and Android. "
            "Looking to launch in 4-6 weeks. What's the ballpark cost and scope?"
        )
    },
    "branding_pack": {
        "title": "🎨 Brand Identity & Social Pack",
        "profession": "Graphic & Brand Designer",
        "currency": "INR",
        "rate_tier": "standard",
        "message": (
            "Hi, starting a handcrafted candle brand named 'AromaKrafts'. "
            "Need a minimalist logo (primary + icon), color palette, brand guidelines, "
            "candle label packaging design (2 sizes), and 6 editable Canva templates for Instagram. "
            "Need it in 10 days. Please send quotation."
        )
    },
    "home_renovation": {
        "title": "🔧 Living Room Renovation & Woodwork",
        "profession": "Interior Contractor",
        "currency": "INR",
        "rate_tier": "standard",
        "message": (
            "Hi sir, want to renovate 14x16 ft living room. Need TV unit with concealed LED lighting, "
            "false ceiling with warm lights, wall panelling, and repainting. "
            "Please share estimated material + labor cost and duration."
        )
    }
}

QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "client_name": {"type": "string"},
        "project_title": {"type": "string"},
        "client_summary": {"type": "string"},
        "currency": {"type": "string"},
        "scope_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "estimated_days": {"type": "number"},
                    "cost": {"type": "number"}
                },
                "required": ["title", "description", "estimated_days", "cost"]
            }
        },
        "out_of_scope": {
            "type": "array",
            "items": {"type": "string"}
        },
        "timeline_summary": {"type": "string"},
        "milestones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "phase": {"type": "string"},
                    "timeline": {"type": "string"},
                    "description": {"type": "string"}
                },
                "required": ["phase", "timeline", "description"]
            }
        },
        "payment_terms": {"type": "string"},
        "whatsapp_reply": {"type": "string"},
        "email_proposal": {"type": "string"}
    },
    "required": [
        "client_name", "project_title", "client_summary", "currency",
        "scope_items", "out_of_scope", "timeline_summary", "milestones",
        "payment_terms", "whatsapp_reply", "email_proposal"
    ]
}


# ---------- Storage ----------

def load_quotes():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_quote(quote_data):
    quotes = load_quotes()
    # Check if exists, update or prepend
    existing_idx = next((i for i, q in enumerate(quotes) if q.get("id") == quote_data.get("id")), None)
    if existing_idx is not None:
        quotes[existing_idx] = quote_data
    else:
        quotes.insert(0, quote_data)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(quotes, f, indent=2, ensure_ascii=False)


# ---------- Ollama AI Integration ----------

def generate_quote_ai(profession, currency, rate_tier, message, your_name="Vikram"):
    system_prompt = f"""You are QuoteCraft, an expert business consultant and pricing estimator for freelancers and solo businesses.
Your role: Convert messy, informal client inquiries into an accurate, structured quotation and scope-of-work.

Freelancer Name: {your_name}
Profession: {profession}
Currency: {currency}
Pricing Tier: {rate_tier} (budget = competitive/affordable, standard = fair market rate, premium = high-end agency)

Rules:
1. Extract realistic line items matching the inquiry. Realistic pricing in {currency}.
2. OUT OF SCOPE items are CRUCIAL: protect the freelancer against scope creep (e.g. domain/hosting fees, paid third-party APIs, extra revisions, copywriting, photography).
3. Generate 'whatsapp_reply': A polite, concise, enthusiastic WhatsApp message proposing this quote, formatted with WhatsApp bold (*text*), line breaks, and professional emojis.
4. Generate 'email_proposal': A formal, complete email proposal.
5. You MUST return ONLY valid JSON matching the exact schema. No markdown fences, no text outside JSON."""

    user_prompt = f"Client Inquiry Message:\n\"\"\"{message}\"\"\""

    payload = {
        "model": TEXT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "format": QUOTE_SCHEMA,
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        content = result["message"]["content"].strip()

    # Clean markdown fences if any model leaked them
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content.strip())
    quote = json.loads(content)

    quote["id"] = str(uuid.uuid4())[:8]
    quote["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    quote["profession"] = profession
    quote["your_name"] = your_name
    quote["raw_inquiry"] = message
    quote["currency"] = currency

    # Calculate total
    total = sum(item.get("cost", 0) for item in quote.get("scope_items", []))
    quote["total_cost"] = total

    return quote


# ---------- HTML Template ----------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuoteCraft — WhatsApp Inquiry to Professional Quotation</title>
<style>
  :root {
    --primary: #2563eb;
    --primary-hover: #1d4ed8;
    --whatsapp: #25d366;
    --whatsapp-dark: #128c7e;
    --bg: #f8fafc;
    --card: #ffffff;
    --text: #0f172a;
    --text-muted: #64748b;
    --border: #e2e8f0;
    --border-focus: #3b82f6;
    --danger: #ef4444;
    --success-bg: #ecfdf5;
    --success-text: #065f46;
    --badge-bg: #eff6ff;
    --badge-text: #1e40af;
    --out-scope-bg: #fef2f2;
    --out-scope-border: #fecaca;
    --out-scope-text: #991b1b;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; }
  body { background: var(--bg); color: var(--text); line-height: 1.5; padding-bottom: 60px; }

  header {
    background: #ffffff;
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.25rem; color: #1e293b; }
  .brand-badge { background: #dbeafe; color: #1e40af; font-size: 0.72rem; padding: 3px 8px; border-radius: 999px; font-weight: 600; }
  .local-tag { display: flex; align-items: center; gap: 6px; font-size: 0.8rem; color: #047857; background: #d1fae5; padding: 4px 10px; border-radius: 999px; font-weight: 600; }
  .local-dot { width: 8px; height: 8px; background: #10b981; border-radius: 50%; }

  .container { max-width: 1100px; margin: 24px auto; padding: 0 16px; display: grid; grid-template-columns: 1fr; gap: 24px; }
  @media (min-width: 900px) {
    .container { grid-template-columns: 420px 1fr; }
  }

  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 22px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
  h2 { font-size: 1.15rem; font-weight: 700; margin-bottom: 14px; color: #1e293b; display: flex; align-items: center; justify-content: space-between; }
  h3 { font-size: 1rem; font-weight: 600; margin-bottom: 8px; color: #334155; }

  label { display: block; font-size: 0.82rem; font-weight: 600; color: #475569; margin-bottom: 6px; }
  input, select, textarea {
    width: 100%;
    padding: 9px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 0.92rem;
    margin-bottom: 14px;
    background: #fff;
    color: var(--text);
  }
  input:focus, select:focus, textarea:focus { outline: none; border-color: var(--border-focus); box-shadow: 0 0 0 3px rgba(59,130,246,0.15); }
  textarea { resize: vertical; min-height: 120px; font-family: inherit; }

  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

  .presets { margin-bottom: 16px; }
  .preset-label { font-size: 0.78rem; font-weight: 600; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
  .preset-buttons { display: flex; flex-wrap: wrap; gap: 6px; }
  .btn-preset {
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    color: #334155;
    padding: 5px 9px;
    border-radius: 6px;
    font-size: 0.78rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .btn-preset:hover { background: #e2e8f0; border-color: #94a3b8; color: #0f172a; }

  .btn-primary {
    background: var(--primary);
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 12px 18px;
    font-size: 0.95rem;
    font-weight: 600;
    width: 100%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    transition: background 0.15s ease;
  }
  .btn-primary:hover { background: var(--primary-hover); }
  .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }

  .loading-box {
    display: none;
    padding: 24px;
    text-align: center;
    background: #f8fafc;
    border: 2px dashed #cbd5e1;
    border-radius: 10px;
    margin-top: 14px;
  }
  .spinner {
    width: 32px;
    height: 32px;
    border: 3px solid #e2e8f0;
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto 12px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Output side */
  .quote-header {
    border-bottom: 2px solid var(--border);
    padding-bottom: 16px;
    margin-bottom: 18px;
  }
  .quote-title { font-size: 1.35rem; font-weight: 700; color: #0f172a; margin-bottom: 4px; }
  .quote-meta { display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.85rem; color: var(--text-muted); }
  .quote-meta strong { color: var(--text); }

  .summary-box {
    background: #f8fafc;
    border-left: 4px solid var(--primary);
    padding: 12px 16px;
    border-radius: 4px;
    font-size: 0.92rem;
    margin-bottom: 20px;
    color: #334155;
  }

  .table-responsive { width: 100%; overflow-x: auto; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  th { background: #f1f5f9; padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; border-bottom: 1px solid var(--border); }
  td { padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:hover td { background: #f8fafc; }

  .item-title { font-weight: 600; color: #1e293b; margin-bottom: 2px; }
  .item-desc { font-size: 0.8rem; color: var(--text-muted); }
  .editable-input { border: 1px solid transparent; background: transparent; padding: 4px 6px; border-radius: 4px; width: 100%; font-size: inherit; font-family: inherit; margin: 0; }
  .editable-input:focus { border-color: var(--border-focus); background: #fff; }
  .cost-input { text-align: right; font-weight: 600; width: 100px; }
  .days-input { text-align: center; width: 60px; }

  .total-row { background: #f8fafc; font-weight: 700; font-size: 1.05rem; }
  .total-row td { padding: 14px 12px; border-top: 2px solid #cbd5e1; }

  .section-badge { display: inline-block; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; padding: 3px 8px; border-radius: 4px; font-weight: 700; margin-bottom: 8px; }
  .badge-out { background: var(--out-scope-bg); color: var(--out-scope-text); border: 1px solid var(--out-scope-border); }
  .badge-in { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }

  .out-scope-box {
    background: #fffafa;
    border: 1px solid #fee2e2;
    border-radius: 8px;
    padding: 14px;
    margin-bottom: 20px;
  }
  .out-scope-box ul { list-style: disc; padding-left: 20px; font-size: 0.88rem; color: #991b1b; }
  .out-scope-box li { margin-bottom: 4px; }

  .milestones-box {
    background: #f8fafc;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
    margin-bottom: 20px;
  }
  .milestone-item { display: flex; gap: 12px; margin-bottom: 10px; font-size: 0.88rem; }
  .milestone-time { background: #e2e8f0; color: #334155; font-weight: 600; font-size: 0.78rem; padding: 2px 8px; border-radius: 4px; height: fit-content; white-space: nowrap; }

  /* Action buttons */
  .actions-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 20px;
    padding-top: 18px;
    border-top: 1px solid var(--border);
  }
  .btn-action {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 9px 14px;
    border-radius: 8px;
    font-size: 0.86rem;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid var(--border);
    background: #fff;
    color: #334155;
    transition: all 0.15s ease;
  }
  .btn-action:hover { background: #f1f5f9; color: #0f172a; }
  .btn-whatsapp { background: #25d366; color: #fff; border-color: #25d366; }
  .btn-whatsapp:hover { background: #128c7e; border-color: #128c7e; color: #fff; }

  .copy-toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: #0f172a;
    color: #fff;
    padding: 10px 18px;
    border-radius: 8px;
    font-size: 0.88rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    display: none;
    z-index: 999;
  }

  .tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
  .tab-btn {
    background: none;
    border: none;
    padding: 8px 16px;
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--text-muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
  }
  .tab-btn.active { color: var(--primary); border-bottom-color: var(--primary); }

  .tab-content { display: none; }
  .tab-content.active { display: block; }

  .history-item {
    border-bottom: 1px solid var(--border);
    padding: 10px 0;
    font-size: 0.85rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .history-item:last-child { border-bottom: none; }
  .history-title { font-weight: 600; color: #1e293b; }
  .history-meta { font-size: 0.75rem; color: var(--text-muted); }

  /* Print Stylesheet for PDF/Client export */
  @media print {
    body { background: #fff; color: #000; padding: 0; }
    header, .input-column, .actions-bar, .tabs, .btn-preset, .presets, .history-card { display: none !important; }
    .container { grid-template-columns: 1fr; max-width: 100%; margin: 0; padding: 0; }
    .card { border: none; box-shadow: none; padding: 0; }
    .editable-input { border: none !important; }
    .print-only-header { display: block !important; margin-bottom: 24px; border-bottom: 2px solid #333; padding-bottom: 12px; }
  }
  .print-only-header { display: none; }
</style>
</head>
<body>

<header>
  <div class="brand">
    <span>💼 QuoteCraft</span>
    <span class="brand-badge">Side Hustle Edition</span>
  </div>
  <div class="local-tag" title="Runs completely on your local laptop using Llama 3.2 via Ollama">
    <span class="local-dot"></span>
    <span>100% Offline AI • Zero Cloud Cost • Private</span>
  </div>
</header>

<div class="container">
  <!-- Left column: Input Form -->
  <div class="input-column">
    <div class="card">
      <h2>
        <span>New Client Inquiry</span>
      </h2>

      <!-- Preset clickers -->
      <div class="presets">
        <div class="preset-label">Quick Real-World Presets:</div>
        <div class="preset-buttons">
          <button class="btn-preset" onclick="loadPreset('bakery_web')">🧁 Bakery Website</button>
          <button class="btn-preset" onclick="loadPreset('wedding_photo')">📸 Wedding Shoot</button>
          <button class="btn-preset" onclick="loadPreset('fitness_app')">📱 Fitness App MVP</button>
          <button class="btn-preset" onclick="loadPreset('branding_pack')">🎨 Brand & Social</button>
          <button class="btn-preset" onclick="loadPreset('home_renovation')">🔧 Living Room Work</button>
        </div>
      </div>

      <form id="quoteForm" onsubmit="generateQuote(event)">
        <label for="yourName">Your Name / Agency</label>
        <input type="text" id="yourName" name="yourName" value="Vikram" required>

        <label for="profession">Your Service / Profession</label>
        <input type="text" id="profession" name="profession" value="Freelance Web Developer" required>

        <div class="row">
          <div>
            <label for="currency">Currency</label>
            <select id="currency" name="currency">
              <option value="INR" selected>₹ INR (Rupees)</option>
              <option value="USD">$ USD (US Dollars)</option>
              <option value="EUR">€ EUR (Euros)</option>
              <option value="GBP">£ GBP (Pounds)</option>
              <option value="CAD">$ CAD (Canadian $)</option>
              <option value="AUD">$ AUD (Australian $)</option>
            </select>
          </div>
          <div>
            <label for="rateTier">Pricing Tier</label>
            <select id="rateTier" name="rateTier">
              <option value="standard" selected>Standard Market</option>
              <option value="budget">Budget Friendly</option>
              <option value="premium">Premium Agency</option>
            </select>
          </div>
        </div>

        <label for="clientMessage">Client's WhatsApp / Email Message</label>
        <textarea id="clientMessage" name="clientMessage" placeholder="Paste the messy client inquiry message here..." required>hi vikram! need a landing page for our boutique bakery in dehradun with menu, photo gallery, online order enquiry form connected to whatsapp, and google maps location. we have logo and photos ready. how much will this cost and can we get it before diwali? also need 3 revisions and basic seo.</textarea>

        <button type="submit" id="btnSubmit" class="btn-primary">
          <span>✨ Generate Quotation & Scope</span>
        </button>
      </form>

      <div id="loadingBox" class="loading-box">
        <div class="spinner"></div>
        <div style="font-weight: 600; color: #1e293b; margin-bottom: 4px;">Llama 3.2 is analyzing client requirements...</div>
        <div style="font-size: 0.8rem; color: var(--text-muted);">Extracting deliverables, estimating timeline, & building anti-scope creep guardrails</div>
      </div>
    </div>

    <!-- Past Quotes History Card -->
    <div class="card history-card" style="margin-top: 20px;">
      <h2><span>Recent Quotes</span> <span style="font-size:0.78rem; font-weight:normal; color:var(--text-muted);" id="historyCount"></span></h2>
      <div id="historyList">
        <div style="font-size: 0.85rem; color: var(--text-muted); text-align: center; padding: 12px 0;">No saved quotes yet.</div>
      </div>
    </div>
  </div>

  <!-- Right column: Generated Quotation & Export -->
  <div class="output-column">
    <div class="card" id="outputCard">
      <!-- Printable header (only shown when printing) -->
      <div class="print-only-header">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
          <div>
            <h1 style="font-size: 1.6rem; color: #0f172a;" id="printBrandName">Vikram Rautela</h1>
            <p style="color: #475569; font-size: 0.9rem;" id="printProfession">Freelance Web Developer</p>
          </div>
          <div style="text-align: right;">
            <h2 style="font-size: 1.2rem; color: #2563eb; margin: 0;">OFFICIAL QUOTATION</h2>
            <p style="font-size: 0.85rem; color: #64748b;">Quote Ref: <span id="printQuoteId">#QC-101</span></p>
            <p style="font-size: 0.85rem; color: #64748b;">Date: <span id="printDate">2026-10-14</span></p>
          </div>
        </div>
      </div>

      <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('breakdown')">📋 Scope & Estimate</button>
        <button class="tab-btn" onclick="switchTab('whatsapp')">💬 WhatsApp Reply</button>
        <button class="tab-btn" onclick="switchTab('email')">✉️ Email Proposal</button>
      </div>

      <!-- Tab 1: Scope & Breakdown -->
      <div id="tab-breakdown" class="tab-content active">
        <div class="quote-header">
          <div class="quote-title" id="outTitle">Boutique Bakery Landing Page</div>
          <div class="quote-meta">
            <div>Client: <strong id="outClient">Client</strong></div>
            <div>Timeline: <strong id="outTimeline">10-14 Days</strong></div>
            <div>Currency: <strong id="outCurrency">INR (₹)</strong></div>
          </div>
        </div>

        <div class="summary-box" id="outSummary">
          Landing page design and build for a boutique bakery in Dehradun, showcasing the menu, photo gallery, WhatsApp order inquiry, and Google Maps location.
        </div>

        <h3 style="margin-bottom: 8px;">Itemized Deliverables & Scope of Work</h3>
        <div class="table-responsive">
          <table id="scopeTable">
            <thead>
              <tr>
                <th>Deliverable / Task</th>
                <th style="width: 80px; text-align: center;">Days</th>
                <th style="width: 120px; text-align: right;">Cost (<span class="curr-sym">₹</span>)</th>
                <th style="width: 40px;"></th>
              </tr>
            </thead>
            <tbody id="scopeTableBody">
              <!-- Populated dynamically -->
            </tbody>
            <tfoot>
              <tr class="total-row">
                <td colspan="2">Total Estimated Investment</td>
                <td style="text-align: right;" id="outTotalCost">₹ 0</td>
                <td></td>
              </tr>
            </tfoot>
          </table>
        </div>

        <div style="margin-bottom: 20px;">
          <button type="button" class="btn-action" onclick="addEmptyRow()">➕ Add Custom Line Item</button>
        </div>

        <!-- Out of scope: The anti-scope-creep shield -->
        <div class="out-scope-box">
          <div class="section-badge badge-out">⚠️ Strictly Out of Scope (Protects Against Scope Creep)</div>
          <ul id="outScopeList">
            <li>Paid domain registration and annual web hosting charges (paid directly by client)</li>
            <li>Copywriting and content writing for individual menu items (provided by client)</li>
            <li>Revisions exceeding the 3 included review rounds (billed at hourly rate)</li>
          </ul>
        </div>

        <!-- Milestones & Payment terms -->
        <div class="milestones-box">
          <div class="section-badge badge-in">📅 Project Milestones & Delivery Schedule</div>
          <div id="milestonesList">
            <!-- Dynamic milestones -->
          </div>
          <div style="font-size: 0.85rem; color: #475569; margin-top: 10px; border-top: 1px dashed var(--border); padding-top: 8px;">
            <strong>Payment Terms:</strong> <span id="outPaymentTerms">40% advance deposit to commence work, 60% upon final delivery & sign-off.</span>
          </div>
        </div>
      </div>

      <!-- Tab 2: WhatsApp reply -->
      <div id="tab-whatsapp" class="tab-content">
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">
          Ready to paste directly into WhatsApp. Pre-formatted with bold text (*text*) and clean emojis.
        </p>
        <textarea id="whatsappOutput" style="min-height: 280px; font-family: monospace; font-size: 0.9rem;" readonly></textarea>
        <button class="btn-action btn-whatsapp" onclick="copyWhatsApp()">
          <span>📋 Copy WhatsApp Message</span>
        </button>
      </div>

      <!-- Tab 3: Formal Email proposal -->
      <div id="tab-email" class="tab-content">
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">
          Formal proposal ready to send via email or client portal.
        </p>
        <textarea id="emailOutput" style="min-height: 300px; font-family: monospace; font-size: 0.9rem;" readonly></textarea>
        <button class="btn-action" onclick="copyEmail()">
          <span>📋 Copy Email Text</span>
        </button>
      </div>

      <!-- Action buttons bottom bar -->
      <div class="actions-bar">
        <button class="btn-action btn-whatsapp" onclick="copyWhatsApp()">
          <span>💬 Copy WhatsApp Reply</span>
        </button>
        <button class="btn-action" onclick="copyEmail()">
          <span>✉️ Copy Email</span>
        </button>
        <button class="btn-action" onclick="window.print()">
          <span>🖨️ Print / Save as PDF</span>
        </button>
        <button class="btn-action" onclick="saveCurrentQuote()">
          <span>💾 Save to Log</span>
        </button>
      </div>

    </div>
  </div>
</div>

<div id="toast" class="copy-toast">Copied to clipboard! 📋</div>

<script>
  let currentQuote = null;
  const presets = {{ presets | tojson }};

  function loadPreset(key) {
    const p = presets[key];
    if (!p) return;
    document.getElementById("profession").value = p.profession;
    document.getElementById("currency").value = p.currency;
    document.getElementById("rateTier").value = p.rate_tier;
    document.getElementById("clientMessage").value = p.message;
  }

  function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    if (tabId === 'breakdown') {
      document.querySelector(".tab-btn:nth-child(1)").classList.add("active");
      document.getElementById("tab-breakdown").classList.add("active");
    } else if (tabId === 'whatsapp') {
      document.querySelector(".tab-btn:nth-child(2)").classList.add("active");
      document.getElementById("tab-whatsapp").classList.add("active");
    } else if (tabId === 'email') {
      document.querySelector(".tab-btn:nth-child(3)").classList.add("active");
      document.getElementById("tab-email").classList.add("active");
    }
  }

  function showToast(msg) {
    const t = document.getElementById("toast");
    t.innerText = msg;
    t.style.display = "block";
    setTimeout(() => { t.style.display = "none"; }, 2500);
  }

  function copyWhatsApp() {
    const txt = document.getElementById("whatsappOutput").value;
    navigator.clipboard.writeText(txt).then(() => {
      showToast("WhatsApp message copied! 💬 Ready to paste.");
    });
  }

  function copyEmail() {
    const txt = document.getElementById("emailOutput").value;
    navigator.clipboard.writeText(txt).then(() => {
      showToast("Email proposal copied! ✉️");
    });
  }

  async function generateQuote(e) {
    e.preventDefault();
    const btn = document.getElementById("btnSubmit");
    const loading = document.getElementById("loadingBox");
    btn.disabled = true;
    loading.style.display = "block";

    const payload = {
      your_name: document.getElementById("yourName").value,
      profession: document.getElementById("profession").value,
      currency: document.getElementById("currency").value,
      rate_tier: document.getElementById("rateTier").value,
      message: document.getElementById("clientMessage").value
    };

    try {
      const resp = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await resp.json();
      if (data.error) {
        alert("Error: " + data.error);
      } else {
        renderQuote(data);
        showToast("Quote generated successfully with Llama 3.2! 🚀");
        loadHistory();
      }
    } catch (err) {
      alert("Failed to connect to local QuoteCraft server: " + err);
    } finally {
      btn.disabled = false;
      loading.style.display = "none";
    }
  }

  function renderQuote(q) {
    currentQuote = q;
    const currSym = getCurrencySymbol(q.currency);
    document.querySelectorAll(".curr-sym").forEach(el => el.innerText = currSym);

    // Header info
    document.getElementById("outTitle").innerText = q.project_title || "Project Quotation";
    document.getElementById("outClient").innerText = q.client_name || "Client";
    document.getElementById("outTimeline").innerText = q.timeline_summary || "Flexible";
    document.getElementById("outCurrency").innerText = `${q.currency} (${currSym})`;
    document.getElementById("outSummary").innerText = q.client_summary || "";

    // Print headers
    document.getElementById("printBrandName").innerText = q.your_name || "Freelancer";
    document.getElementById("printProfession").innerText = q.profession || "Independent Professional";
    document.getElementById("printQuoteId").innerText = "#QC-" + (q.id || "101");
    document.getElementById("printDate").innerText = q.created_at ? q.created_at.split(" ")[0] : new Date().toISOString().split("T")[0];

    // Table
    const tbody = document.getElementById("scopeTableBody");
    tbody.innerHTML = "";
    (q.scope_items || []).forEach((item, idx) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <input type="text" class="editable-input item-title" value="${escapeHtml(item.title)}" onchange="updateItem(${idx}, 'title', this.value)">
          <input type="text" class="editable-input item-desc" value="${escapeHtml(item.description)}" onchange="updateItem(${idx}, 'description', this.value)">
        </td>
        <td style="text-align: center;">
          <input type="number" class="editable-input days-input" value="${item.estimated_days || 1}" onchange="updateItem(${idx}, 'estimated_days', this.value)">
        </td>
        <td style="text-align: right;">
          <input type="number" class="editable-input cost-input" value="${item.cost || 0}" onchange="updateItem(${idx}, 'cost', this.value)">
        </td>
        <td style="text-align: center;">
          <button style="border:none; background:none; cursor:pointer; color:#ef4444;" onclick="deleteItem(${idx})" title="Remove item">✕</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    // Out of scope
    const oosList = document.getElementById("outScopeList");
    oosList.innerHTML = "";
    (q.out_of_scope || []).forEach(item => {
      const li = document.createElement("li");
      li.innerText = item;
      oosList.appendChild(li);
    });

    // Milestones
    const mList = document.getElementById("milestonesList");
    mList.innerHTML = "";
    (q.milestones || []).forEach(m => {
      const div = document.createElement("div");
      div.className = "milestone-item";
      div.innerHTML = `
        <span class="milestone-time">${escapeHtml(m.timeline || '')}</span>
        <div><strong>${escapeHtml(m.phase || '')}:</strong> ${escapeHtml(m.description || '')}</div>
      `;
      mList.appendChild(div);
    });

    // Payment terms
    document.getElementById("outPaymentTerms").innerText = q.payment_terms || "40% upfront deposit, 60% upon completion.";

    // WhatsApp & Email text
    document.getElementById("whatsappOutput").value = q.whatsapp_reply || "";
    document.getElementById("emailOutput").value = q.email_proposal || "";

    recalculateTotal();
  }

  function updateItem(idx, field, val) {
    if (!currentQuote || !currentQuote.scope_items[idx]) return;
    if (field === 'cost' || field === 'estimated_days') {
      currentQuote.scope_items[idx][field] = Number(val) || 0;
    } else {
      currentQuote.scope_items[idx][field] = val;
    }
    recalculateTotal();
  }

  function deleteItem(idx) {
    if (!currentQuote) return;
    currentQuote.scope_items.splice(idx, 1);
    renderQuote(currentQuote);
  }

  function addEmptyRow() {
    if (!currentQuote) {
      currentQuote = {
        scope_items: [],
        currency: document.getElementById("currency").value
      };
    }
    currentQuote.scope_items.push({
      title: "New Custom Service",
      description: "Deliverable details and scope",
      estimated_days: 1,
      cost: 1000
    });
    renderQuote(currentQuote);
  }

  function recalculateTotal() {
    if (!currentQuote) return;
    const total = (currentQuote.scope_items || []).reduce((sum, item) => sum + (Number(item.cost) || 0), 0);
    currentQuote.total_cost = total;
    const currSym = getCurrencySymbol(currentQuote.currency);
    document.getElementById("outTotalCost").innerText = `${currSym} ${total.toLocaleString()}`;
  }

  function getCurrencySymbol(code) {
    const symbols = { INR: '₹', USD: '$', EUR: '€', GBP: '£', CAD: '$', AUD: '$' };
    return symbols[code] || code;
  }

  function escapeHtml(text) {
    if (!text) return "";
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  async function saveCurrentQuote() {
    if (!currentQuote) return;
    try {
      const res = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentQuote)
      });
      const data = await res.json();
      showToast("Quote saved to local history! 💾");
      loadHistory();
    } catch(err) {
      alert("Failed to save: " + err);
    }
  }

  async function loadHistory() {
    try {
      const res = await fetch("/api/history");
      const list = await res.json();
      const el = document.getElementById("historyList");
      document.getElementById("historyCount").innerText = list.length + " saved";
      if (!list || list.length === 0) {
        el.innerHTML = '<div style="font-size: 0.85rem; color: var(--text-muted); text-align: center; padding: 12px 0;">No saved quotes yet.</div>';
        return;
      }
      el.innerHTML = "";
      list.slice(0, 5).forEach(item => {
        const row = document.createElement("div");
        row.className = "history-item";
        const sym = getCurrencySymbol(item.currency);
        row.innerHTML = `
          <div>
            <div class="history-title">${escapeHtml(item.project_title || 'Untitled')}</div>
            <div class="history-meta">${escapeHtml(item.client_name || 'Client')} • ${item.created_at || ''}</div>
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 600; color: #1e293b;">${sym} ${(item.total_cost || 0).toLocaleString()}</div>
            <button style="border:none; background:none; color:var(--primary); font-size:0.75rem; cursor:pointer;" onclick='loadHistoryItem(${JSON.stringify(item)})'>Load</button>
          </div>
        `;
        el.appendChild(row);
      });
    } catch(e) {
      console.error(e);
    }
  }

  function loadHistoryItem(item) {
    renderQuote(item);
    showToast("Loaded saved quote: " + (item.project_title || ''));
  }

  // Load initial preset on startup
  window.addEventListener("DOMContentLoaded", () => {
    loadHistory();
    // Pre-render default sample
    const sampleQuote = {
      id: "demo01",
      client_name: "Anita (Boutique Bakery)",
      project_title: "Boutique Bakery Landing Page",
      client_summary: "High-converting responsive landing page in Dehradun with interactive menu, photo gallery, WhatsApp direct order integration, and Google Maps location.",
      currency: "INR",
      timeline_summary: "8-10 Business Days",
      profession: "Freelance Web Developer",
      your_name: "Vikram",
      scope_items: [
        {
          title: "UI/UX Design & Responsive Layout",
          description: "Mobile-first modern design matching bakery aesthetic and colors",
          estimated_days: 3,
          cost: 7500
        },
        {
          title: "Digital Menu & Photo Gallery",
          description: "Filterable product menu categories with high-res photo gallery showcase",
          estimated_days: 2,
          cost: 5000
        },
        {
          title: "WhatsApp Order Inquiry & Maps Integration",
          description: "One-tap WhatsApp ordering with pre-filled cart/message and Google Maps embed",
          estimated_days: 2,
          cost: 4500
        },
        {
          title: "On-Page SEO & Speed Optimization",
          description: "Meta tags, schema markup for local Dehradun bakery search, and 90+ Lighthouse speed",
          estimated_days: 1,
          cost: 3000
        }
      ],
      out_of_scope: [
        "Domain purchase & annual cloud hosting fees (client will purchase directly or provide access)",
        "Food photography & copywriting for menu item descriptions (provided by client)",
        "Payment gateway merchant account registration (direct WhatsApp orders are included)",
        "Revisions exceeding 3 review rounds (billed separately at ₹800/hr)"
      ],
      milestones: [
        { phase: "Phase 1: Discovery & Wireframe", timeline: "Days 1-2", description: "Collect bakery photos, menu list, and wireframe review" },
        { phase: "Phase 2: Development & Integrations", timeline: "Days 3-6", description: "Build landing page, WhatsApp integration, and mobile testing" },
        { phase: "Phase 3: Client Review & Launch", timeline: "Days 7-9", description: "3 revision rounds, domain DNS setup, and go-live before Diwali" }
      ],
      payment_terms: "40% upfront advance (₹8,000) to schedule start date, 60% upon final delivery & client launch approval.",
      whatsapp_reply: "Hi Anita! 🧁 Thanks so much for reaching out.\\n\\nI'd love to build the landing page for your bakery in Dehradun! Here is a quick quotation and timeline:\\n\\n*Scope:*\\n• Custom mobile-friendly design with your logo & photos\\n• Interactive menu & photo gallery\\n• Direct WhatsApp ordering button (customers tap to order)\\n• Google Maps location & local SEO\\n• 3 review rounds included\\n\\n*Timeline:* 8-10 business days (well before Diwali! 🪔)\\n*Total Investment:* ₹20,000 (40% advance to start)\\n\\nDoes this work for you? If yes, I can share the invoice and get started this Wednesday! 🙌",
      email_proposal: "Dear Anita,\\n\\nThank you for considering my web development services for your boutique bakery in Dehradun.\\n\\nBased on your requirements, I have prepared an itemized scope of work and quotation.\\n\\nKey Deliverables:\\n1. Custom Responsive Landing Page: Mobile-optimized showcase for your brand\\n2. Digital Menu & Photo Gallery: Easy browsing for cakes and baked goods\\n3. Direct WhatsApp Ordering: Seamless friction-free order inquiries\\n4. Local SEO & Maps Setup: High visibility for Dehradun walk-in customers\\n5. 3 Revision Rounds: Ensuring the design matches your exact vision\\n\\nTimeline: 8-10 business days\\nTotal Investment: INR 20,000\\nPayment Terms: 40% advance deposit upon agreement, 60% upon project completion and launch.\\n\\nPlease let me know if you would like any adjustments to this scope.\\n\\nWarm regards,\\nVikram Rautela"
    };
    renderQuote(sampleQuote);
  });
</script>

</body>
</html>
"""


# ---------- Flask Routes ----------

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, presets=PRESETS)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400

    profession = data.get("profession", "Freelance Professional")
    currency = data.get("currency", "INR")
    rate_tier = data.get("rate_tier", "standard")
    your_name = data.get("your_name", "Vikram")

    try:
        quote = generate_quote_ai(profession, currency, rate_tier, message, your_name)
        save_quote(quote)
        return jsonify(quote)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json() or {}
    if not data:
        return jsonify({"error": "No data provided"}), 400
    save_quote(data)
    return jsonify({"status": "saved", "id": data.get("id")})


@app.route("/api/history")
def api_history():
    return jsonify(load_quotes())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting QuoteCraft on http://0.0.0.0:{port}")
    print(f"Using local Ollama model: {TEXT_MODEL} ({OLLAMA_URL})")
    app.run(host="0.0.0.0", port=port, debug=True)

