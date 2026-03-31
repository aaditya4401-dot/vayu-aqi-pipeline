-- Intermediate: Average AQI per zone per hour
-- Combines AQI readings and station data to produce hourly zone-level aggregates

with aqi_data as (
    select * from {{ ref('stg_aqi') }}
),

stations as (
    select * from {{ source('vayu_raw', 'dim_stations') }}
),

hourly_zone as (
    select
        s.zone,
        date_trunc('hour', a.timestamp_utc) as hour_utc,
        date_trunc('hour', a.timestamp_ist) as hour_ist,
        extract(hour from a.timestamp_ist) as hour_of_day_ist,

        count(*) as reading_count,

        -- AQI aggregates
        round(avg(a.aqi)::numeric) as avg_aqi,
        min(a.aqi) as min_aqi,
        max(a.aqi) as max_aqi,

        -- Category of the average
        case
            when round(avg(a.aqi)::numeric) <= 50 then 'Good'
            when round(avg(a.aqi)::numeric) <= 100 then 'Satisfactory'
            when round(avg(a.aqi)::numeric) <= 200 then 'Moderate'
            when round(avg(a.aqi)::numeric) <= 300 then 'Poor'
            when round(avg(a.aqi)::numeric) <= 400 then 'Very Poor'
            else 'Severe'
        end as avg_aqi_category,

        -- Key pollutant averages
        round(avg(a.pm25)::numeric, 1) as avg_pm25,
        round(avg(a.pm10)::numeric, 1) as avg_pm10,
        round(avg(a.no2)::numeric, 1) as avg_no2,
        round(avg(a.o3)::numeric, 1) as avg_o3,

        -- Most common dominant pollutant in this hour+zone
        mode() within group (order by a.dominant_pollutant) as dominant_pollutant

    from aqi_data a
    join stations s on a.location_id = s.location_id
    group by s.zone, date_trunc('hour', a.timestamp_utc),
             date_trunc('hour', a.timestamp_ist),
             extract(hour from a.timestamp_ist)
)

select * from hourly_zone
