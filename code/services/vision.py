import base64
import json
import mimetypes
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from openai import OpenAI

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_FILE)

class VisionService:
    """
    Extracts structured financial facts from images.

    This service does NOT make affordability decisions.
    It only extracts facts visible in the image.
    """

    MODEL = "mistralai/mistral-large-2512"

    def __init__(self):
        api_key = os.getenv("getenv")

        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not configured"
            )

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.xkiro.com/v1",
        )

    def extract_financial_facts(
        self,
        image_path: str,
        image_id: str | None = None,
        related_event_id: str | None = None,
    ) -> dict:

        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Image not found: {image_path}"
            )

        mime_type, _ = mimetypes.guess_type(path.name)

        if not mime_type:
            mime_type = "image/png"

        image_bytes = path.read_bytes()

        encoded_image = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        image_data_url = (
            f"data:{mime_type};base64,{encoded_image}"
        )
        prompt = """
        You are a financial document extraction system. You read a single image
        that contains a receipt, invoice, order summary, payment confirmation,
        bank alert, or similar financial document.
        
        EXTRACT the FINAL amount payable. If the final total is not visible
        (image is cropped, cut off, or unclear), extract the LAST VISIBLE amount
        that represents a running total or item bill — do NOT return null.
        
        =====================================================================
        LABEL PRIORITY (highest first)
        =====================================================================
        1. "Grand Total", "Final Total", "Total Amount"
        2. "Amount Paid", "Amount Payable", "Amount Due", "You Pay", "Paid"
        3. "Total Payable", "Net Payable", "Net Amount", "Balance Due"
        4. "Order Total", "Bill Total", "Invoice Total"
        5. "Total"
        6. "Item Bill", "Subtotal" (ONLY as fallback when nothing better is visible)
        7. The last visible running total on the document
        
        Prefer the LOWER-positioned match. Bills list subtotals first and the
        final total last.
        
        =====================================================================
        NEVER RETURN
        =====================================================================
        - Individual line-item prices (e.g., "Milk 200g  75.00")
        - "Qty", "Quantity", "Total Items"
        - Tax lines: GST, VAT, CGST, SGST, IGST, Service Tax
        - Delivery / Shipping / Handling / Platform fee
        - Negative numbers (discounts, cashback, wallet credits)
        - A section heading like "TOTAL ORDER BILL DETAILS" — that's a
          heading, not an amount. Look for the amount to the RIGHT of it.
        
        =====================================================================
        CROPPED IMAGES — IMPORTANT
        =====================================================================
        If the image is cropped at the bottom and the final total is not
        visible:
          - DO NOT return null.
          - Return the last visible amount (e.g., "Item Bill" ₹2,854.00).
          - Set confidence to 0.5–0.7.
          - In `evidence`, state: "Image appears cropped; returned last
            visible amount."
        
        A slightly-wrong number is FAR better than null.
        
        =====================================================================
        SANITY CHECKS
        =====================================================================
        Before finalizing:
          1. amount is a positive number (not 0, not negative).
          2. Not an individual line-item price (those are listed vertically
             with descriptions next to them).
          3. If both subtotal and total exist, you returned the total.
          4. If a discount exists, you returned the amount AFTER the discount
             (unless the final total is not visible — then use the pre-discount
             amount as fallback).
        
        =====================================================================
        CURRENCY
        =====================================================================
        Detect from ₹, Rs, INR, Rp, IDR, $, USD, €, EUR, £, GBP, ¥, JPY,
        R, ZAR. Return ISO 4217 code.
        
        =====================================================================
        OUTPUT (JSON only, no markdown, no commentary)
        =====================================================================
        {
          "document_type": null,
          "merchant": null,
          "amount": null,
          "currency": null,
          "date": null,
          "amount_label": null,
          "confidence": 0.0,
          "evidence": null
        }
        
        Rules:
        - amount: positive number, or null ONLY if truly no number is visible
        - confidence: 0.9+ for PREFER-level labels; 0.5–0.7 for fallback
        - date: YYYY-MM-DD if visible
        - currency: ISO 4217 code (INR, USD, EUR, etc.)
        - amount_label: exact visible label of the row you used
        - evidence: ONE sentence stating which row you used and where;
          mention if image appeared cropped
        """
        MAX_ATTEMPTS = 3
        last_error = None
    
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.MODEL,
                    temperature=0,
                    max_tokens=700,
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Extract the financial facts from this image.",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_data_url},
                                },
                            ],
                        },
                    ],
                )
    
                raw = response.choices[0].message.content
                facts = self._parse_json(raw)
    
                return {
                    "image_id": image_id,
                    "related_event_id": related_event_id,
                    "facts": facts,
                    "image_path": str(path),
                    "attempt": attempt,
                }
    
            except Exception as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS:
                    import time
                    time.sleep(1.5 * attempt)   # simple backoff
                    continue
    
        raise RuntimeError(
            f"Vision extraction failed after {MAX_ATTEMPTS} attempts "
            f"for {image_path}: {last_error}"
        )

    @staticmethod
    def _parse_json(text: str | None) -> dict:
        """
        Parse JSON returned by the vision model.
        Handles markdown fences and empty responses.
        """
    
        if text is None:
            raise ValueError(
                "Vision model returned no text content."
            )
    
        text = text.strip()
    
        if not text:
            raise ValueError(
                "Vision model returned an empty response."
            )
    
        # Remove markdown code fences.
        if text.startswith("```"):
            lines = text.splitlines()
    
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
    
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
    
            text = "\n".join(lines).strip()
    
        try:
            result = json.loads(text)
    
        except json.JSONDecodeError:
    
            # Try finding a JSON object inside surrounding text.
            match = re.search(
                r"\{.*\}",
                text,
                flags=re.DOTALL,
            )
    
            if not match:
                raise ValueError(
                    "Vision model did not return valid JSON.\n"
                    f"Raw response:\n{text}"
                )
    
            try:
                result = json.loads(match.group(0))
    
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Vision model returned malformed JSON.\n"
                    f"Raw response:\n{text}"
                ) from exc
    
        if not isinstance(result, dict):
            raise ValueError(
                "Vision model response must be a JSON object."
            )
    
        return result