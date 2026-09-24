"""Timeline events from online pharmacy orders: order placed, delivered or picked up, not approved."""

from __future__ import annotations


def events(conn, patient_id: str, since) -> list[dict]:
    return conn.execute(
        """
        WITH ev AS (
            SELECT o.placed_at AS at, 'pharmacy_order' AS type,
                   'Medicine order placed · ' || o.number AS title,
                   (SELECT count(*) FROM pharmacy_order_items i WHERE i.order_id = o.id)::text
                       || ' item(s) · ' || CASE o.fulfillment WHEN 'delivery' THEN 'home delivery'
                                                  ELSE 'pickup at the clinic pharmacy' END AS detail,
                   'neutral' AS tone, o.id::text AS ref_id
            FROM pharmacy_orders o WHERE o.patient_id = %(p)s

            UNION ALL
            SELECT o.completed_at, 'pharmacy_order_completed',
                   CASE o.status WHEN 'delivered' THEN 'Medicines delivered · ' ELSE 'Medicines picked up · ' END
                       || o.number,
                   (SELECT string_agg(i.name, ', ' ORDER BY i.name) FROM pharmacy_order_items i WHERE i.order_id = o.id),
                   'neutral', o.id::text
            FROM pharmacy_orders o
            WHERE o.patient_id = %(p)s AND o.status IN ('delivered', 'picked_up') AND o.completed_at IS NOT NULL

            UNION ALL
            SELECT o.reviewed_at, 'pharmacy_order_rejected', 'Medicine order not approved · ' || o.number,
                   'The pharmacist explained why in the order', 'alert', o.id::text
            FROM pharmacy_orders o
            WHERE o.patient_id = %(p)s AND o.status = 'rejected' AND o.reviewed_at IS NOT NULL
        )
        SELECT * FROM ev
        WHERE %(since)s::timestamptz IS NULL OR at >= %(since)s::timestamptz
        """,
        {"p": patient_id, "since": since},
    ).fetchall()
