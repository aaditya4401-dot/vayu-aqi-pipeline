-- Staging: Clean weather readings with derived fields
-- Source: weather_readings fact table
-- Derives: wind_from_northwest flag, heat_index, wind_chill, IST timestamp

with source as (
    select * from {{ source('vayu_raw', 'weather_readings') }}
),

staged as (
    select
        id,
        location_id,
        timestamp as timestamp_utc,
        -- Convert UTC to IST (UTC + 5:30)
        timestamp + interval '5 hours 30 minutes' as timestamp_ist,

        -- Core measurements
        temperature_celsius,
        humidity_percent,
        pressure_hpa,
        wind_speed_mps,
        wind_direction_deg,
        coalesce(visibility_m, 10000) as visibility_m,
        coalesce(clouds_percent, 0) as clouds_percent,
        description as weather_description,
        source as data_source,
        ingested_at,

        -- Derived: wind from northwest (270-360 deg) carries Punjab stubble smoke
        case
            when wind_direction_deg >= 270 and wind_direction_deg <= 360 then true
            else false
        end as wind_from_northwest,

        -- Derived: cardinal wind direction
        case
            when wind_direction_deg >= 337.5 or wind_direction_deg < 22.5 then 'N'
            when wind_direction_deg >= 22.5 and wind_direction_deg < 67.5 then 'NE'
            when wind_direction_deg >= 67.5 and wind_direction_deg < 112.5 then 'E'
            when wind_direction_deg >= 112.5 and wind_direction_deg < 157.5 then 'SE'
            when wind_direction_deg >= 157.5 and wind_direction_deg < 202.5 then 'S'
            when wind_direction_deg >= 202.5 and wind_direction_deg < 247.5 then 'SW'
            when wind_direction_deg >= 247.5 and wind_direction_deg < 292.5 then 'W'
            when wind_direction_deg >= 292.5 and wind_direction_deg < 337.5 then 'NW'
        end as wind_cardinal,

        -- Derived: simple heat index approximation (Steadman, valid for T > 27C and RH > 40%)
        case
            when temperature_celsius > 27 and humidity_percent > 40 then
                round((-8.785 + 1.611 * temperature_celsius + 2.339 * humidity_percent
                - 0.1461 * temperature_celsius * humidity_percent)::numeric, 1)
            else temperature_celsius
        end as heat_index_celsius,

        -- Derived: wind stagnation (low wind traps pollution)
        round((1.0 / (wind_speed_mps + 0.1))::numeric, 3) as wind_stagnation_index,

        -- Derived: season
        case
            when extract(month from timestamp) in (12, 1, 2) then 'winter'
            when extract(month from timestamp) in (3, 4, 5) then 'summer'
            when extract(month from timestamp) in (6, 7, 8, 9) then 'monsoon'
            else 'post_monsoon'
        end as season

    from source
)

select * from staged
