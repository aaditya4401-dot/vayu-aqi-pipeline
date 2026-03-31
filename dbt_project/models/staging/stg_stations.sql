-- Staging: Clean ground station measurements with zone labels
-- Source: station_measurements fact table
-- Joins dim_stations for zone info

with source as (
    select * from {{ source('vayu_raw', 'station_measurements') }}
),

stations as (
    select * from {{ source('vayu_raw', 'dim_stations') }}
),

staged as (
    select
        sm.id,
        sm.station_id,
        sm.location_id,
        s.name as station_name,
        s.zone,
        sm.timestamp as timestamp_utc,
        sm.timestamp + interval '5 hours 30 minutes' as timestamp_ist,

        -- Pollutant readings (ug/m3)
        sm.pm25,
        sm.pm10,
        coalesce(sm.no2, 0) as no2,
        coalesce(sm.so2, 0) as so2,
        coalesce(sm.o3, 0) as o3,
        coalesce(sm.co, 0) as co,

        -- Station-level weather
        sm.temperature_celsius,
        sm.humidity_percent,

        -- PM2.5 to PM10 ratio (indicator of combustion vs dust pollution)
        case
            when sm.pm10 > 0 then round((sm.pm25 / sm.pm10)::numeric, 3)
            else null
        end as pm25_pm10_ratio,

        -- Derived AQI from PM2.5 using CPCB breakpoints
        case
            when sm.pm25 <= 30 then round((sm.pm25 * 50.0 / 30.0)::numeric)::int
            when sm.pm25 <= 60 then round((50 + (sm.pm25 - 30) * 50.0 / 30.0)::numeric)::int
            when sm.pm25 <= 90 then round((100 + (sm.pm25 - 60) * 100.0 / 30.0)::numeric)::int
            when sm.pm25 <= 120 then round((200 + (sm.pm25 - 90) * 100.0 / 30.0)::numeric)::int
            when sm.pm25 <= 250 then round((300 + (sm.pm25 - 120) * 100.0 / 130.0)::numeric)::int
            else round((400 + (sm.pm25 - 250) * 100.0 / 250.0)::numeric)::int
        end as derived_aqi,

        sm.source as data_source,
        sm.ingested_at

    from source sm
    left join stations s on sm.location_id = s.location_id
)

select * from staged
