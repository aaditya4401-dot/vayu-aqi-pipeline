-- Mart: All detected anomalies with station context
-- Enriches raw anomaly_log with station names, zones, and recent AQI context

with anomalies as (
    select * from {{ source('vayu_raw', 'anomaly_log') }}
),

stations as (
    select * from {{ source('vayu_raw', 'dim_stations') }}
),

recent_aqi as (
    select * from {{ ref('stg_aqi') }}
),

enriched as (
    select
        an.id as anomaly_id,
        an.location_id,
        s.name as station_name,
        s.zone,
        an.timestamp as anomaly_timestamp_utc,
        an.timestamp + interval '5 hours 30 minutes' as anomaly_timestamp_ist,
        an.metric,
        round(an.value::numeric, 1) as observed_value,
        round(an.expected_value::numeric, 1) as expected_value,
        round(an.z_score::numeric, 2) as z_score,
        an.method as detection_method,
        an.severity,

        -- Severity ranking for sorting
        case an.severity
            when 'critical' then 1
            when 'high' then 2
            when 'medium' then 3
            when 'low' then 4
            else 5
        end as severity_rank,

        an.description,
        an.detected_at

    from anomalies an
    left join stations s on an.location_id = s.location_id
)

select * from enriched
order by anomaly_timestamp_utc desc, severity_rank asc
