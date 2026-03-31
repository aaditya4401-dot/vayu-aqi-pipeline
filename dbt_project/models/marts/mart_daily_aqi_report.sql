-- Mart: Daily AQI summary per zone
-- Business-ready daily report with min/max/avg, dominant pollutant, worst hour

with hourly as (
    select * from {{ ref('int_hourly_zone_aqi') }}
),

daily_summary as (
    select
        zone,
        date_trunc('day', hour_utc) as report_date,

        -- AQI aggregates
        round(avg(avg_aqi)::numeric) as daily_avg_aqi,
        min(min_aqi) as daily_min_aqi,
        max(max_aqi) as daily_max_aqi,

        -- Daily category based on average
        case
            when round(avg(avg_aqi)::numeric) <= 50 then 'Good'
            when round(avg(avg_aqi)::numeric) <= 100 then 'Satisfactory'
            when round(avg(avg_aqi)::numeric) <= 200 then 'Moderate'
            when round(avg(avg_aqi)::numeric) <= 300 then 'Poor'
            when round(avg(avg_aqi)::numeric) <= 400 then 'Very Poor'
            else 'Severe'
        end as daily_aqi_category,

        -- Pollutant averages
        round(avg(avg_pm25)::numeric, 1) as daily_avg_pm25,
        round(avg(avg_pm10)::numeric, 1) as daily_avg_pm10,
        round(avg(avg_no2)::numeric, 1) as daily_avg_no2,
        round(avg(avg_o3)::numeric, 1) as daily_avg_o3,

        -- Most common dominant pollutant across the day
        mode() within group (order by dominant_pollutant) as daily_dominant_pollutant,

        -- Worst hour of the day (IST)
        (array_agg(hour_of_day_ist order by avg_aqi desc))[1] as worst_hour_ist,
        max(avg_aqi) as worst_hour_aqi,

        -- Best hour of the day (IST)
        (array_agg(hour_of_day_ist order by avg_aqi asc))[1] as best_hour_ist,
        min(avg_aqi) as best_hour_aqi,

        -- How many hours of data we have
        count(*) as hours_of_data

    from hourly
    group by zone, date_trunc('day', hour_utc)
)

select * from daily_summary
order by report_date desc, daily_avg_aqi desc
