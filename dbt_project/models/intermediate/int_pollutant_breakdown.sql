-- Intermediate: Which pollutant drives AQI at each station
-- Unpivots pollutant concentrations to enable per-pollutant analysis

with aqi_data as (
    select * from {{ ref('stg_aqi') }}
),

stations as (
    select * from {{ source('vayu_raw', 'dim_stations') }}
),

-- Unpivot pollutants into rows for easier analysis
breakdown as (
    select
        a.location_id,
        s.name as station_name,
        s.zone,
        a.timestamp_utc,
        a.timestamp_ist,
        a.aqi,
        a.aqi_category,
        pollutant.name as pollutant,
        pollutant.value as concentration_ugm3,
        pollutant.naaqs_standard,

        -- How many times over the standard
        round((pollutant.value / nullif(pollutant.naaqs_standard, 0))::numeric, 2)
            as times_over_standard,

        -- Is this the dominant pollutant for this reading?
        case when pollutant.name = a.dominant_pollutant then true else false end
            as is_dominant

    from aqi_data a
    join stations s on a.location_id = s.location_id
    cross join lateral (
        values
            ('PM2.5', a.pm25, 60.0),
            ('PM10',  a.pm10, 100.0),
            ('NO2',   a.no2,  80.0),
            ('SO2',   a.so2,  80.0),
            ('O3',    a.o3,   100.0),
            ('CO',    a.co,   4000.0)
    ) as pollutant(name, value, naaqs_standard)
)

select * from breakdown
