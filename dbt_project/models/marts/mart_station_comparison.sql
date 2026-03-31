-- Mart: Cross-station comparison - which zone is worst?
-- Aggregates latest data per station for side-by-side comparison

with aqi_data as (
    select * from {{ ref('stg_aqi') }}
),

station_data as (
    select * from {{ ref('stg_stations') }}
),

stations as (
    select * from {{ source('vayu_raw', 'dim_stations') }}
),

-- Get the latest reading per location from AQI
latest_aqi as (
    select distinct on (location_id)
        location_id,
        timestamp_utc,
        aqi,
        aqi_category,
        pm25,
        pm10,
        no2,
        so2,
        o3,
        co,
        dominant_pollutant,
        pm25_exceeds_who
    from aqi_data
    order by location_id, timestamp_utc desc
),

-- Get the latest station reading per location
latest_station as (
    select distinct on (location_id)
        location_id,
        pm25 as station_pm25,
        pm10 as station_pm10,
        derived_aqi as station_derived_aqi,
        pm25_pm10_ratio,
        temperature_celsius,
        humidity_percent
    from station_data
    order by location_id, timestamp_utc desc
),

comparison as (
    select
        s.location_id,
        s.name as station_name,
        s.zone,
        s.latitude,
        s.longitude,

        -- Latest AQI data
        la.aqi as latest_aqi,
        la.aqi_category,
        la.pm25,
        la.pm10,
        la.dominant_pollutant,
        la.pm25_exceeds_who,
        la.timestamp_utc as aqi_updated_at,

        -- Latest station data
        ls.station_pm25,
        ls.station_pm10,
        ls.station_derived_aqi,
        ls.pm25_pm10_ratio,
        ls.temperature_celsius,
        ls.humidity_percent,

        -- Cross-source consistency check
        case
            when la.pm25 is not null and ls.station_pm25 is not null then
                round(abs(la.pm25 - ls.station_pm25)::numeric, 1)
            else null
        end as pm25_source_delta,

        -- Rank stations by AQI (1 = worst)
        rank() over (order by la.aqi desc) as aqi_rank_worst,
        rank() over (order by la.aqi asc) as aqi_rank_best

    from stations s
    left join latest_aqi la on s.location_id = la.location_id
    left join latest_station ls on s.location_id = ls.location_id
)

select * from comparison
order by aqi_rank_worst asc
