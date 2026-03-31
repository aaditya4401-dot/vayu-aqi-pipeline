-- Intermediate: Weather + AQI aligned by location and timestamp
-- Core join for causality analysis and feature engineering

with weather as (
    select * from {{ ref('stg_weather') }}
),

aqi as (
    select * from {{ ref('stg_aqi') }}
),

joined as (
    select
        w.location_id,
        w.timestamp_utc,
        w.timestamp_ist,
        w.season,

        -- Weather fields
        w.temperature_celsius,
        w.humidity_percent,
        w.pressure_hpa,
        w.wind_speed_mps,
        w.wind_direction_deg,
        w.wind_cardinal,
        w.wind_from_northwest,
        w.visibility_m,
        w.clouds_percent,
        w.heat_index_celsius,
        w.wind_stagnation_index,
        w.weather_description,

        -- AQI fields
        a.aqi,
        a.aqi_category,
        a.severity_color,
        a.pm25,
        a.pm10,
        a.no2,
        a.so2,
        a.o3,
        a.co,
        a.nh3,
        a.dominant_pollutant,
        a.pm25_exceeds_who,

        -- Derived interaction features
        -- Moisture trap: humid air holds more particulates
        round((w.humidity_percent * a.pm25 / 100.0)::numeric, 1) as moisture_trap_index,

        -- Ventilation: high wind + clear sky = good dispersion
        round((w.wind_speed_mps * (100 - w.clouds_percent) / 100.0)::numeric, 2) as ventilation_proxy,

        -- Temperature inversion indicator (low temp + high humidity + low wind)
        case
            when w.temperature_celsius < 15
                 and w.humidity_percent > 70
                 and w.wind_speed_mps < 2 then true
            else false
        end as inversion_likely

    from weather w
    inner join aqi a
        on w.location_id = a.location_id
        and date_trunc('hour', w.timestamp_utc) = date_trunc('hour', a.timestamp_utc)
)

select * from joined
