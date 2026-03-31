-- Staging: Clean AQI readings with Indian categories and dominant pollutant
-- Source: aqi_readings fact table
-- Derives: aqi_category (Indian scale), dominant_pollutant, severity color

with source as (
    select * from {{ source('vayu_raw', 'aqi_readings') }}
),

staged as (
    select
        id,
        location_id,
        timestamp as timestamp_utc,
        timestamp + interval '5 hours 30 minutes' as timestamp_ist,

        -- AQI value and Indian category
        aqi,
        case
            when aqi <= 50 then 'Good'
            when aqi <= 100 then 'Satisfactory'
            when aqi <= 200 then 'Moderate'
            when aqi <= 300 then 'Poor'
            when aqi <= 400 then 'Very Poor'
            else 'Severe'
        end as aqi_category,

        -- Severity color (for dashboard)
        case
            when aqi <= 50 then 'green'
            when aqi <= 100 then 'light_green'
            when aqi <= 200 then 'yellow'
            when aqi <= 300 then 'orange'
            when aqi <= 400 then 'red'
            else 'maroon'
        end as severity_color,

        -- Pollutant concentrations (all in ug/m3)
        pm25,
        pm10,
        no2,
        so2,
        o3,
        co,
        nh3,

        -- Derived: dominant pollutant (which is highest relative to its standard)
        -- Using Indian NAAQS 24-hr standards for comparison
        case
            when greatest(
                pm25 / 60.0,   -- NAAQS 24hr standard for PM2.5
                pm10 / 100.0,  -- PM10
                no2 / 80.0,    -- NO2
                so2 / 80.0,    -- SO2
                o3 / 100.0,    -- O3
                co / 4000.0    -- CO (4 mg/m3 = 4000 ug/m3)
            ) = pm25 / 60.0 then 'PM2.5'
            when greatest(
                pm25 / 60.0, pm10 / 100.0, no2 / 80.0,
                so2 / 80.0, o3 / 100.0, co / 4000.0
            ) = pm10 / 100.0 then 'PM10'
            when greatest(
                pm25 / 60.0, pm10 / 100.0, no2 / 80.0,
                so2 / 80.0, o3 / 100.0, co / 4000.0
            ) = no2 / 80.0 then 'NO2'
            when greatest(
                pm25 / 60.0, pm10 / 100.0, no2 / 80.0,
                so2 / 80.0, o3 / 100.0, co / 4000.0
            ) = so2 / 80.0 then 'SO2'
            when greatest(
                pm25 / 60.0, pm10 / 100.0, no2 / 80.0,
                so2 / 80.0, o3 / 100.0, co / 4000.0
            ) = o3 / 100.0 then 'O3'
            else 'CO'
        end as dominant_pollutant,

        -- WHO guideline exceedance flags
        case when pm25 > 15 then true else false end as pm25_exceeds_who,
        case when pm10 > 45 then true else false end as pm10_exceeds_who,
        case when no2 > 25 then true else false end as no2_exceeds_who,

        source as data_source,
        ingested_at

    from source
)

select * from staged
